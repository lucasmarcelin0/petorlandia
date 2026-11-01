"""Entrada de mercadoria pelo XML da NF-e de compra.

1. ``importar_xml`` lê a nota, recusa duplicada ou de outro CNPJ e grava um
   rascunho com sugestão para cada item: o vínculo já usado com o mesmo
   fornecedor, o código de barras (GTIN) ou, sem nada disso, criar produto.
2. A loja confere (``salvar_conferencia``): vincula, cria ou ignora cada
   item, ajusta o fator da embalagem (caixa com 12 → 12) e o preço de venda.
3. ``lancar_entrada`` cria os produtos novos (fora da loja online), soma o
   estoque com o custo de cada item e grava o vínculo para a próxima nota.
4. ``estornar_entrada`` devolve o estoque se a nota foi lançada por engano.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
import io
from typing import Any, Iterable, Optional
import zipfile

from sqlalchemy.exc import IntegrityError

from extensions import db
from models import (
    CasaDeRacao,
    LojaEntradaItem,
    LojaEntradaNota,
    LojaFiscalConfig,
    LojaFornecedorProduto,
    Product,
    ProductVariant,
)
from providers.nfe.chave import only_digits
from providers.nfe.leitor_compra import NotaCompraInvalida, ler_nota_compra
from services.loja_caixa import estoque
from services.loja_caixa.estoque import EstoqueError
from time_utils import now_in_brazil


CENT = Decimal("0.01")
MARGEM_PADRAO = Decimal("50")
MAX_ARQUIVO = 1024 * 1024  # 1 MB por XML
MAX_ARQUIVOS_ZIP = 100
UNIDADES_VENDA = ["UN", "KG", "G", "L", "ML", "CX", "PCT", "SC", "FD", "M", "PAR", "KIT"]


class EntradaError(ValueError):
    """Erro com mensagem pronta para a tela de entradas."""


def _cnpj_da_loja(casa: CasaDeRacao) -> str:
    config = LojaFiscalConfig.query.filter_by(casa_de_racao_id=casa.id).first()
    return only_digits((config.cnpj if config else None) or casa.cnpj)


def _variantes_da_loja(casa_id: int):
    return ProductVariant.query.join(Product, ProductVariant.product_id == Product.id).filter(
        Product.casa_de_racao_id == casa_id
    )


def _preco_sugerido(custo_unitario: Decimal, margem: Decimal = MARGEM_PADRAO) -> Decimal:
    if custo_unitario <= 0:
        return Decimal("0")
    return (custo_unitario * (Decimal("1") + margem / Decimal("100"))).quantize(CENT, ROUND_HALF_UP)


def _unidade_venda(unidade_compra: str, fator: Decimal) -> str:
    """Caixa/fardo com fator > 1 vira unidade; KG, L etc. ficam como estão."""
    unidade = (unidade_compra or "UN").upper()
    if fator > 1 or unidade not in UNIDADES_VENDA:
        return "UN"
    return unidade


def _sugerir(casa_id: int, fornecedor_cnpj: str, item: LojaEntradaItem, gtin_trib_fator: Decimal) -> None:
    """Preenche ação, produto e fator sugeridos para um item recém-importado."""
    vinculo = None
    if fornecedor_cnpj and item.codigo_fornecedor:
        vinculo = LojaFornecedorProduto.query.filter_by(
            casa_de_racao_id=casa_id,
            fornecedor_cnpj=fornecedor_cnpj,
            codigo_fornecedor=item.codigo_fornecedor,
        ).first()
    if vinculo is not None and vinculo.product is not None:
        item.acao = "vincular"
        item.product_id = vinculo.product_id
        item.variant_id = vinculo.variant_id
        item.fator = vinculo.fator or Decimal("1")
        item.sugestao = "fornecedor"
        return

    variantes = _variantes_da_loja(casa_id)
    if item.gtin:
        variant = variantes.filter(ProductVariant.barcode == item.gtin).first()
        if variant is not None:
            item.acao, item.product_id, item.variant_id = "vincular", variant.product_id, variant.id
            item.fator = Decimal("1")
            item.sugestao = "codigo_barras"
            return
    if item.gtin_trib and item.gtin_trib != item.gtin:
        # Código da unidade de venda (ex.: o sachê dentro da caixa).
        variant = variantes.filter(ProductVariant.barcode == item.gtin_trib).first()
        if variant is not None:
            item.acao, item.product_id, item.variant_id = "vincular", variant.product_id, variant.id
            item.fator = gtin_trib_fator
            item.sugestao = "codigo_barras"
            return

    item.acao = "criar"
    item.fator = gtin_trib_fator
    item.unidade_venda = _unidade_venda(item.unidade_compra, gtin_trib_fator)
    item.preco_venda = _preco_sugerido(item.custo_unitario)
    item.sugestao = None


def importar_xml(
    casa: CasaDeRacao, conteudo: bytes, *, usuario_id: int | None = None, origem: str = "upload"
) -> LojaEntradaNota:
    if len(conteudo or b"") > MAX_ARQUIVO:
        raise EntradaError("O XML passa de 1 MB. Confira se é mesmo o XML da nota.")
    try:
        nota = ler_nota_compra(conteudo)
    except NotaCompraInvalida as exc:
        raise EntradaError(str(exc)) from exc

    cnpj_loja = _cnpj_da_loja(casa)
    if cnpj_loja and nota.destinatario_documento and nota.destinatario_documento != cnpj_loja:
        raise EntradaError(
            f"A nota {nota.numero} de {nota.fornecedor_nome} é para outro CNPJ/CPF, não para esta loja."
        )
    existente = LojaEntradaNota.query.filter_by(casa_de_racao_id=casa.id, chave=nota.chave).first()
    if existente is not None:
        raise EntradaError(f"A nota {nota.numero} de {nota.fornecedor_nome} já foi importada.")

    entrada = LojaEntradaNota(
        casa_de_racao_id=casa.id,
        chave=nota.chave,
        numero=nota.numero[:9],
        serie=nota.serie[:3],
        dh_emi=(nota.dh_emi or "")[:32] or None,
        fornecedor_cnpj=nota.fornecedor_cnpj[:14] or None,
        fornecedor_nome=nota.fornecedor_nome,
        valor_total=nota.valor_total,
        protocolo=(nota.protocolo or "")[:20] or None,
        autorizada=nota.autorizada,
        origem=origem,
        status="rascunho",
        xml=conteudo.decode("utf-8", errors="replace"),
        created_by_id=usuario_id,
    )
    db.session.add(entrada)
    for dado in nota.itens:
        item = LojaEntradaItem(
            n_item=dado.n_item,
            codigo_fornecedor=dado.codigo or f"ITEM{dado.n_item}",
            descricao=dado.descricao,
            gtin=dado.gtin,
            gtin_trib=dado.gtin_trib,
            ncm=dado.ncm,
            cest=dado.cest,
            origem=(dado.origem or "")[:1] or None,
            unidade_compra=dado.unidade or "UN",
            quantidade_compra=dado.quantidade,
            valor_total=dado.custo_total,
        )
        entrada.itens.append(item)
        _sugerir(casa.id, entrada.fornecedor_cnpj, item, dado.fator_sugerido)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise EntradaError(f"A nota {nota.numero} já foi importada.") from exc
    return entrada


def importar_arquivos(
    casa: CasaDeRacao, arquivos: Iterable[tuple[str, bytes]], *, usuario_id: int | None = None
) -> dict[str, list]:
    """Importa XMLs soltos ou dentro de .zip. Devolve importadas e erros."""
    resultado: dict[str, list] = {"importadas": [], "erros": []}

    def _um(nome: str, conteudo: bytes) -> None:
        try:
            resultado["importadas"].append(importar_xml(casa, conteudo, usuario_id=usuario_id))
        except EntradaError as exc:
            resultado["erros"].append(f"{nome}: {exc}")

    for nome, conteudo in arquivos:
        nome = nome or "arquivo"
        if nome.lower().endswith(".zip"):
            try:
                pacote = zipfile.ZipFile(io.BytesIO(conteudo))
            except zipfile.BadZipFile:
                resultado["erros"].append(f"{nome}: arquivo .zip inválido.")
                continue
            xmls = [i for i in pacote.infolist() if i.filename.lower().endswith(".xml") and not i.is_dir()]
            if len(xmls) > MAX_ARQUIVOS_ZIP:
                resultado["erros"].append(f"{nome}: envie no máximo {MAX_ARQUIVOS_ZIP} notas por .zip.")
                continue
            for info in xmls:
                if info.file_size > MAX_ARQUIVO:
                    resultado["erros"].append(f"{info.filename}: passa de 1 MB.")
                    continue
                _um(info.filename, pacote.read(info))
        else:
            _um(nome, conteudo)
    return resultado


# ------------------------------------------------------------- conferência

def _decimal(valor, padrao: Optional[Decimal] = None) -> Optional[Decimal]:
    if valor in (None, ""):
        return padrao
    try:
        return estoque.decimal_de(valor)
    except EstoqueError:
        return padrao


def salvar_conferencia(entrada: LojaEntradaNota, dados: dict[str, Any]) -> list[str]:
    """Grava o que a loja escolheu para cada item. Devolve avisos dos campos
    inválidos, que ficam com o valor anterior; com aviso, não lance a nota."""
    if entrada.status != "rascunho":
        raise EntradaError("Esta nota já foi lançada.")
    avisos: list[str] = []
    for item in entrada.itens:
        prefixo = f"item_{item.id}_"
        acao = dados.get(prefixo + "acao") or item.acao
        if acao not in {"vincular", "criar", "ignorar"}:
            acao = item.acao
        item.acao = acao
        bruto = dados.get(prefixo + "fator")
        fator = _decimal(bruto) if bruto not in (None, "") else Decimal(item.fator or 1)
        if fator is None or fator <= 0:
            # Mantém o fator anterior e avisa: o lançamento fica bloqueado até corrigir.
            avisos.append(f"Item {item.n_item}: fator inválido ({bruto}). Use um número maior que zero.")
            fator = Decimal(item.fator or 1)
        item.fator = fator
        if acao == "vincular":
            variant_id = dados.get(prefixo + "variant_id")
            product_id = dados.get(prefixo + "product_id")
            if variant_id or product_id:
                item.variant_id = int(variant_id) if variant_id else None
                item.product_id = int(product_id) if product_id else None
        elif acao == "criar":
            preco = _decimal(dados.get(prefixo + "preco_venda"), item.preco_venda)
            item.preco_venda = preco.quantize(CENT) if preco is not None else None
            unidade = (dados.get(prefixo + "unidade_venda") or item.unidade_venda or "UN").upper()
            item.unidade_venda = unidade if unidade in UNIDADES_VENDA else "UN"
            nome = " ".join((dados.get(prefixo + "nome") or "").split())[:120]
            if nome:
                item.descricao = nome
    db.session.commit()
    return avisos


def _validar(entrada: LojaEntradaNota) -> list[str]:
    erros = []
    for item in entrada.itens:
        if item.acao == "ignorar":
            continue
        if item.acao == "vincular":
            product = db.session.get(Product, item.product_id) if item.product_id else None
            if product is None or product.casa_de_racao_id != entrada.casa_de_racao_id:
                erros.append(f"Item {item.n_item} ({item.descricao}): escolha o produto da loja.")
                continue
            if item.variant_id:
                variant = db.session.get(ProductVariant, item.variant_id)
                if variant is None or variant.product_id != product.id:
                    erros.append(f"Item {item.n_item}: apresentação inválida.")
                    continue
            unidade = estoque.unidade_de(product)
        else:
            if not item.preco_venda or item.preco_venda <= 0:
                erros.append(f"Item {item.n_item} ({item.descricao}): informe o preço de venda.")
                continue
            unidade = item.unidade_venda or "UN"
        quantidade = item.quantidade_estoque
        if quantidade <= 0:
            erros.append(f"Item {item.n_item}: quantidade inválida.")
        elif unidade not in estoque.UNIDADES_FRACIONADAS and quantidade != quantidade.to_integral_value():
            erros.append(
                f"Item {item.n_item} ({item.descricao}): {estoque.formatar_quantidade(quantidade, 'KG')} "
                f"unidades não fecha um número inteiro. Ajuste o fator da embalagem ou a unidade."
            )
    return erros


def _criar_produto(entrada: LojaEntradaNota, item: LojaEntradaItem) -> tuple[Product, ProductVariant]:
    preco = float(item.preco_venda)
    product = Product(
        casa_de_racao_id=entrada.casa_de_racao_id,
        name=item.descricao[:120],
        price=preco,
        stock=0,
        status="inactive",  # entra fora da loja online; a loja publica quando quiser
        ncm=item.ncm,
        cest=item.cest,
        origem=item.origem,
        unidade=item.unidade_venda or "UN",
    )
    codigo = item.gtin_trib if Decimal(item.fator or 1) > 1 and item.gtin_trib else (item.gtin or item.gtin_trib)
    if codigo and _variantes_da_loja(entrada.casa_de_racao_id).filter(ProductVariant.barcode == codigo).first():
        codigo = None
    variant = ProductVariant(name="Padrão", price=preco, stock=0, status="active", position=0, barcode=codigo)
    product.variants.append(variant)
    db.session.add(product)
    db.session.flush()
    return product, variant


def _travar_nota(entrada: LojaEntradaNota) -> LojaEntradaNota:
    """Bloqueia a nota e os saldos dos produtos dela até o commit: um clique
    duplo não lança duas vezes e duas notas do mesmo produto não se apagam."""
    entrada = LojaEntradaNota.query.filter_by(id=entrada.id).with_for_update().populate_existing().one()
    itens = [item for item in entrada.itens if item.acao != "ignorar"]
    estoque.travar_saldos((item.product_id for item in itens), (item.variant_id for item in itens))
    return entrada


def lancar_entrada(entrada: LojaEntradaNota, *, usuario_id: int | None = None) -> LojaEntradaNota:
    entrada = _travar_nota(entrada)
    if entrada.status != "rascunho":
        raise EntradaError("Esta nota já foi lançada.")
    erros = _validar(entrada)
    if erros:
        raise EntradaError(" ".join(erros[:5]))
    try:
        for item in entrada.itens:
            if item.acao == "ignorar":
                continue
            if item.acao == "criar":
                product, variant = _criar_produto(entrada, item)
                item.product_id, item.variant_id = product.id, variant.id
            else:
                product = db.session.get(Product, item.product_id)
                variant = db.session.get(ProductVariant, item.variant_id) if item.variant_id else None
                if variant is None and product.active_variants:
                    variant = product.active_variants[0]
                    item.variant_id = variant.id
                # Completa o cadastro fiscal que estiver faltando.
                if not product.ncm and item.ncm:
                    product.ncm = item.ncm
                if not product.cest and item.cest:
                    product.cest = item.cest
                codigo = item.gtin if Decimal(item.fator or 1) == 1 else item.gtin_trib
                if variant is not None and not variant.barcode and codigo:
                    if not _variantes_da_loja(entrada.casa_de_racao_id).filter(ProductVariant.barcode == codigo).first():
                        variant.barcode = codigo
            custo = item.custo_unitario
            if variant is not None:
                variant.custo = custo
            estoque.movimentar(
                casa_de_racao_id=entrada.casa_de_racao_id,
                product=product,
                variant=variant,
                quantidade=item.quantidade_estoque,
                tipo="entrada_nota",
                referencia_tipo="entrada",
                referencia_id=entrada.id,
                usuario_id=usuario_id,
                custo_unitario=custo,
                observacao=f"NF {entrada.numero} {entrada.fornecedor_nome or ''}".strip(),
            )
            _gravar_vinculo(entrada, item)
    except EstoqueError as exc:
        db.session.rollback()
        raise EntradaError(str(exc)) from exc
    entrada.status = "lancada"
    entrada.lancada_em = now_in_brazil()
    entrada.lancada_por_id = usuario_id
    db.session.commit()
    return entrada


def _gravar_vinculo(entrada: LojaEntradaNota, item: LojaEntradaItem) -> None:
    if not entrada.fornecedor_cnpj or not item.codigo_fornecedor or not item.product_id:
        return
    vinculo = LojaFornecedorProduto.query.filter_by(
        casa_de_racao_id=entrada.casa_de_racao_id,
        fornecedor_cnpj=entrada.fornecedor_cnpj,
        codigo_fornecedor=item.codigo_fornecedor,
    ).first()
    if vinculo is None:
        vinculo = LojaFornecedorProduto(
            casa_de_racao_id=entrada.casa_de_racao_id,
            fornecedor_cnpj=entrada.fornecedor_cnpj,
            codigo_fornecedor=item.codigo_fornecedor,
        )
        db.session.add(vinculo)
    vinculo.product_id = item.product_id
    vinculo.variant_id = item.variant_id
    vinculo.fator = item.fator or Decimal("1")


def estornar_entrada(entrada: LojaEntradaNota, *, usuario_id: int | None = None) -> LojaEntradaNota:
    entrada = _travar_nota(entrada)
    if entrada.status != "lancada":
        raise EntradaError("Só notas lançadas podem ser estornadas.")
    for item in entrada.itens:
        if item.acao == "ignorar" or not item.product_id:
            continue
        product = db.session.get(Product, item.product_id)
        if product is None:
            continue
        variant = db.session.get(ProductVariant, item.variant_id) if item.variant_id else None
        estoque.movimentar(
            casa_de_racao_id=entrada.casa_de_racao_id,
            product=product,
            variant=variant,
            quantidade=-item.quantidade_estoque,
            tipo="ajuste",
            referencia_tipo="entrada",
            referencia_id=entrada.id,
            usuario_id=usuario_id,
            observacao=f"Estorno da NF {entrada.numero}",
        )
    entrada.status = "estornada"
    entrada.estornada_em = now_in_brazil()
    db.session.commit()
    return entrada


def excluir_rascunho(entrada: LojaEntradaNota) -> None:
    if entrada.status != "rascunho":
        raise EntradaError("Só notas em conferência podem ser excluídas; as lançadas são estornadas.")
    db.session.delete(entrada)
    db.session.commit()
