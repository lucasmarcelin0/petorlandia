"""Caixa da loja (PDV): abertura, vendas de balcão, NFC-e e fechamento.

Ordem de uma venda, pensada para nunca perder dinheiro nem estoque:
    1. valida itens e pagamentos e grava a venda com a baixa de estoque;
    2. só então emite a NFC-e (se ligada). Falha na nota não desfaz a
       venda: ela fica com o aviso e a nota pode ser emitida de novo.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
import logging
import re
from typing import Any, Iterable, Optional
import unicodedata

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import (
    CaixaMovimento,
    CaixaSessao,
    LojaFiscalConfig,
    NfceDocumento,
    Product,
    ProductVariant,
    VendaBalcao,
    VendaBalcaoItem,
    VendaBalcaoPagamento,
)
from models.loja_caixa import FORMAS_PAGAMENTO_CAIXA
from providers.nfce.xml_builder import (
    CSOSN_SN102,
    CSOSN_SN500,
    TPAG_COM_CARD,
    ItemNfce,
    PagamentoNfce,
    cfop_padrao,
    gtin_valido,
)
from providers.nfe.chave import only_digits
from services.loja_caixa import estoque
from services.loja_caixa.estoque import EstoqueError, decimal_de, fracionado, unidade_de
from time_utils import now_in_brazil


logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
QTD = Decimal("0.0001")
ZERO = Decimal("0")
MAX_ITENS = 300


class CaixaError(ValueError):
    """Erro com mensagem pronta para a tela do caixa."""


class VendaRepetida(CaixaError):
    """A chave do caixa já gerou uma venda: nada é cobrado de novo."""

    def __init__(self, venda: VendaBalcao):
        super().__init__("Esta venda já foi registrada.")
        self.venda = venda


def _moeda(valor) -> Decimal:
    return Decimal(valor or 0).quantize(CENT, ROUND_HALF_UP)


def _numero(valor, campo: str) -> Decimal:
    try:
        return decimal_de(valor, campo)
    except EstoqueError as exc:
        raise CaixaError(str(exc)) from exc


# ------------------------------------------------------------------ sessão

def caixa_aberto(casa_id: int) -> Optional[CaixaSessao]:
    return CaixaSessao.query.filter_by(casa_de_racao_id=casa_id, status="aberto").first()


def abrir_caixa(casa_id: int, *, valor_abertura, usuario_id: int | None) -> CaixaSessao:
    if caixa_aberto(casa_id):
        raise CaixaError("Já existe um caixa aberto nesta loja.")
    valor = _moeda(_numero(valor_abertura or "0", "o troco inicial"))
    if valor < 0:
        raise CaixaError("O troco inicial não pode ser negativo.")
    sessao = CaixaSessao(
        casa_de_racao_id=casa_id,
        status="aberto",
        valor_abertura=valor,
        aberto_por_id=usuario_id,
        aberto_em=now_in_brazil(),
    )
    db.session.add(sessao)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise CaixaError("Já existe um caixa aberto nesta loja.") from exc
    return sessao


def _exigir_aberto(sessao: Optional[CaixaSessao], casa_id: int) -> CaixaSessao:
    if sessao is None or sessao.casa_de_racao_id != casa_id or sessao.status != "aberto":
        raise CaixaError("Abra o caixa antes de vender.")
    return sessao


def resumo_caixa(sessao: CaixaSessao) -> dict[str, Any]:
    """Totais da sessão para a tela e para o fechamento."""
    vendas = VendaBalcao.query.filter_by(sessao_id=sessao.id).all()
    concluidas = [v for v in vendas if v.status == "concluida"]
    canceladas = [v for v in vendas if v.status == "cancelada"]
    por_forma: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for venda in concluidas:
        for pagamento in venda.pagamentos:
            por_forma[pagamento.t_pag] += _moeda(pagamento.valor)
        if venda.troco:
            por_forma["01"] -= _moeda(venda.troco)
    sangrias = ZERO
    suprimentos = ZERO
    for movimento in sessao.movimentos.order_by(CaixaMovimento.id).all():
        if movimento.tipo == "sangria":
            sangrias += _moeda(movimento.valor)
        elif movimento.tipo == "suprimento":
            suprimentos += _moeda(movimento.valor)
    dinheiro_vendas = por_forma.get("01", ZERO)
    esperado = _moeda(sessao.valor_abertura) + dinheiro_vendas + suprimentos - sangrias
    formas = [
        {"t_pag": codigo, "rotulo": FORMAS_PAGAMENTO_CAIXA.get(codigo, "Outros"), "valor": por_forma[codigo]}
        for codigo in FORMAS_PAGAMENTO_CAIXA
        if por_forma.get(codigo)
    ]
    return {
        "quantidade_vendas": len(concluidas),
        "total_vendas": sum((_moeda(v.total) for v in concluidas), ZERO),
        "quantidade_canceladas": len(canceladas),
        "total_canceladas": sum((_moeda(v.total) for v in canceladas), ZERO),
        "formas": formas,
        "dinheiro_vendas": dinheiro_vendas,
        "sangrias": sangrias,
        "suprimentos": suprimentos,
        "abertura": _moeda(sessao.valor_abertura),
        "dinheiro_esperado": esperado,
        "notas_pendentes": sum(
            1 for v in concluidas
            if v.emitir_nfce and (v.nfce is None or v.nfce.status != "autorizada")
        ),
    }


def movimentar_caixa(
    sessao: CaixaSessao, *, tipo: str, valor, motivo: str | None, usuario_id: int | None
) -> CaixaMovimento:
    if sessao.status != "aberto":
        raise CaixaError("O caixa está fechado.")
    if tipo not in {"sangria", "suprimento"}:
        raise CaixaError("Movimento inválido.")
    quantia = _moeda(_numero(valor, "o valor"))
    if quantia <= 0:
        raise CaixaError("Informe um valor maior que zero.")
    if tipo == "sangria" and quantia > resumo_caixa(sessao)["dinheiro_esperado"]:
        raise CaixaError("A retirada é maior que o dinheiro previsto no caixa.")
    movimento = CaixaMovimento(
        sessao_id=sessao.id,
        tipo=tipo,
        valor=quantia,
        motivo=" ".join((motivo or "").split())[:255] or None,
        usuario_id=usuario_id,
    )
    db.session.add(movimento)
    db.session.commit()
    return movimento


def fechar_caixa(
    sessao: CaixaSessao, *, valor_contado, usuario_id: int | None, observacao: str | None = None
) -> CaixaSessao:
    if sessao.status != "aberto":
        raise CaixaError("Este caixa já foi fechado.")
    contado = _moeda(_numero(valor_contado, "o dinheiro contado"))
    if contado < 0:
        raise CaixaError("O valor contado não pode ser negativo.")
    sessao.valor_esperado = resumo_caixa(sessao)["dinheiro_esperado"]
    sessao.valor_contado = contado
    sessao.status = "fechado"
    sessao.fechado_por_id = usuario_id
    sessao.fechado_em = now_in_brazil()
    sessao.observacao = " ".join((observacao or "").split())[:255] or None
    db.session.commit()
    return sessao


# ---------------------------------------------------------------- catálogo

def _produtos_da_loja(casa_id: int):
    return Product.query.filter(Product.casa_de_racao_id == casa_id)


def _entrada_catalogo(product: Product, variant: Optional[ProductVariant]) -> dict[str, Any]:
    unidade = unidade_de(product)
    preco = variant.price if variant is not None else product.price
    nome = product.name
    if variant is not None and len(product.active_variants) > 1:
        nome = f"{product.name} — {variant.display_name}"
    codigo_barras = (variant.barcode if variant is not None else None) or ""
    return {
        "product_id": product.id,
        "variant_id": variant.id if variant is not None else None,
        "descricao": nome[:160],
        "preco": f"{_moeda(preco):.2f}",
        "unidade": unidade,
        "fracionado": fracionado(product),
        "estoque": estoque.formatar_quantidade(estoque.saldo(product, variant), unidade),
        "codigo_barras": codigo_barras,
        "sku": (variant.sku if variant is not None else None) or "",
        "sem_ncm": len(only_digits(product.ncm)) != 8,
        "online": product.status == "active",
    }


def _variantes_vendaveis(product: Product) -> list[Optional[ProductVariant]]:
    ativas = product.active_variants
    return list(ativas) if ativas else [None]


def sem_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii").lower()


def produtos_por_nome(query, termo: str, limite: int = 20) -> list[Product]:
    """Busca por palavras ignorando acentos: "racao" acha "Ração".

    O banco pré-filtra com curinga nas letras que podem ter acento (funciona
    igual no PostgreSQL e no SQLite) e o Python confere o nome sem acentos.
    """
    palavras = [re.sub(r"[^a-z0-9]", "", sem_acentos(p)) for p in (termo or "").split()[:5]]
    palavras = [p for p in palavras if p]
    if not palavras:
        return []
    for palavra in palavras:
        padrao = "".join("_" if letra in "aeiouc" else letra for letra in palavra)
        query = query.filter(Product.name.ilike(f"%{padrao}%"))
    encontrados = []
    for product in query.order_by(Product.name).limit(limite * 10).all():
        nome = sem_acentos(product.name)
        if all(palavra in nome for palavra in palavras):
            encontrados.append(product)
            if len(encontrados) >= limite:
                break
    return encontrados


def buscar_itens(casa_id: int, termo: str, limite: int = 20) -> list[dict[str, Any]]:
    """Código de barras ou SKU exatos primeiro; depois nome (todas as palavras)."""
    termo = " ".join((termo or "").split())[:80]
    if not termo:
        return []
    exatos = (
        ProductVariant.query.join(Product, ProductVariant.product_id == Product.id)
        .filter(
            Product.casa_de_racao_id == casa_id,
            ProductVariant.status == "active",
            or_(ProductVariant.barcode == termo, func.lower(ProductVariant.sku) == termo.lower()),
        )
        .limit(limite)
        .all()
    )
    if exatos:
        return [_entrada_catalogo(v.product, v) for v in exatos]

    resultados: list[dict[str, Any]] = []
    for product in produtos_por_nome(_produtos_da_loja(casa_id), termo, limite):
        for variant in _variantes_vendaveis(product):
            resultados.append(_entrada_catalogo(product, variant))
            if len(resultados) >= limite:
                return resultados
    return resultados


def vincular_codigo_barras(casa_id: int, *, product_id: int, variant_id: int | None, codigo: str) -> ProductVariant:
    """Grava o código lido no leitor numa apresentação (para a próxima venda)."""
    codigo = re.sub(r"\s+", "", codigo or "")[:80]
    if not codigo:
        raise CaixaError("Leia ou digite o código de barras.")
    product = _produtos_da_loja(casa_id).filter(Product.id == product_id).first()
    if product is None:
        raise CaixaError("Produto não encontrado nesta loja.")
    variant = None
    if variant_id:
        variant = next((v for v in product.variants if v.id == int(variant_id)), None)
    elif len(product.active_variants) == 1:
        variant = product.active_variants[0]
    if variant is None:
        raise CaixaError("Escolha a apresentação do produto.")
    em_uso = (
        ProductVariant.query.join(Product, ProductVariant.product_id == Product.id)
        .filter(Product.casa_de_racao_id == casa_id, ProductVariant.barcode == codigo, ProductVariant.id != variant.id)
        .first()
    )
    if em_uso is not None:
        raise CaixaError(f"Este código já está em \"{em_uso.product.name}\".")
    variant.barcode = codigo
    db.session.commit()
    return variant


# ------------------------------------------------------------------- venda

def _carregar_produtos(casa_id: int, itens: list[dict[str, Any]]):
    ids = {int(item.get("product_id") or 0) for item in itens}
    produtos = {
        p.id: p
        for p in _produtos_da_loja(casa_id).filter(Product.id.in_(ids)).with_for_update().all()
    }
    variant_ids = {int(item["variant_id"]) for item in itens if item.get("variant_id")}
    variantes = {}
    if variant_ids:
        variantes = {
            v.id: v
            for v in ProductVariant.query.filter(ProductVariant.id.in_(variant_ids)).with_for_update().all()
        }
    return produtos, variantes


def _ratear(valores: list[Decimal], total: Decimal) -> list[Decimal]:
    """Divide ``total`` proporcionalmente; o último absorve o arredondamento."""
    base = sum(valores, ZERO)
    if total <= 0 or base <= 0:
        return [ZERO for _ in valores]
    partes = [(total * valor / base).quantize(CENT, ROUND_HALF_UP) for valor in valores]
    partes[-1] += total - sum(partes, ZERO)
    return partes


def _chave_cliente(valor) -> str | None:
    chave = re.sub(r"[^A-Za-z0-9-]", "", str(valor or ""))[:40]
    return chave or None


def venda_por_chave(casa_id: int, chave) -> Optional[VendaBalcao]:
    chave = _chave_cliente(chave)
    if not chave:
        return None
    return VendaBalcao.query.filter_by(casa_de_racao_id=casa_id, chave_cliente=chave).first()


def registrar_venda(
    casa_id: int,
    sessao: Optional[CaixaSessao],
    *,
    itens: Iterable[dict[str, Any]],
    pagamentos: Iterable[dict[str, Any]],
    desconto_venda=None,
    emitir_nfce: bool = False,
    usuario_id: int | None = None,
    chave_cliente: str | None = None,
) -> VendaBalcao:
    """Valida e grava a venda com a baixa de estoque (sem emitir a nota).

    Com ``chave_cliente`` repetida levanta ``VendaRepetida`` com a venda já
    gravada (nada é cobrado nem baixado de novo).
    """
    chave = _chave_cliente(chave_cliente)
    if chave:
        existente = venda_por_chave(casa_id, chave)
        if existente is not None:
            raise VendaRepetida(existente)
    sessao = _exigir_aberto(sessao, casa_id)
    itens = list(itens or [])
    pagamentos = list(pagamentos or [])
    if not itens:
        raise CaixaError("Adicione ao menos um produto.")
    if len(itens) > MAX_ITENS:
        raise CaixaError(f"Uma venda aceita até {MAX_ITENS} itens.")

    produtos, variantes = _carregar_produtos(casa_id, itens)
    linhas: list[dict[str, Any]] = []
    for entrada in itens:
        product = produtos.get(int(entrada.get("product_id") or 0))
        if product is None:
            raise CaixaError("Um dos produtos não pertence a esta loja.")
        variant = None
        if entrada.get("variant_id"):
            variant = variantes.get(int(entrada["variant_id"]))
            if variant is None or variant.product_id != product.id:
                raise CaixaError(f"Apresentação inválida para \"{product.name}\".")
        quantidade = _numero(entrada.get("quantidade"), "a quantidade").quantize(QTD, ROUND_HALF_UP)
        if quantidade <= 0:
            raise CaixaError(f"Quantidade inválida em \"{product.name}\".")
        if not fracionado(product) and quantidade != quantidade.to_integral_value():
            raise CaixaError(f"\"{product.name}\" é vendido por unidade inteira.")
        preco_cadastro = Decimal(str((variant.price if variant is not None else product.price) or 0))
        preco = preco_cadastro
        if entrada.get("preco_unitario") not in (None, ""):
            preco = _numero(entrada.get("preco_unitario"), "o preço")
        preco = preco.quantize(QTD, ROUND_HALF_UP)
        if preco <= 0:
            raise CaixaError(f"Preço inválido em \"{product.name}\".")
        bruto = (quantidade * preco).quantize(CENT, ROUND_HALF_UP)
        desconto = _moeda(_numero(entrada.get("desconto") or "0", "o desconto"))
        if desconto < 0 or desconto >= bruto:
            raise CaixaError(f"Desconto inválido em \"{product.name}\".")
        linhas.append(
            {"product": product, "variant": variant, "quantidade": quantidade, "preco": preco, "bruto": bruto, "desconto": desconto}
        )

    subtotal = sum((linha["bruto"] for linha in linhas), ZERO)
    desconto_geral = _moeda(_numero(desconto_venda or "0", "o desconto"))
    if desconto_geral < 0:
        raise CaixaError("Desconto inválido.")
    for linha, parte in zip(linhas, _ratear([l["bruto"] - l["desconto"] for l in linhas], desconto_geral)):
        linha["desconto"] += parte
        if linha["desconto"] >= linha["bruto"]:
            raise CaixaError("O desconto não pode zerar um item.")
    desconto_total = sum((linha["desconto"] for linha in linhas), ZERO)
    total = subtotal - desconto_total
    if total <= 0:
        raise CaixaError("O total da venda precisa ser maior que zero.")

    pagos: list[tuple[str, Decimal, str | None]] = []
    for pagamento in pagamentos:
        t_pag = str(pagamento.get("t_pag") or "").strip()
        if t_pag not in FORMAS_PAGAMENTO_CAIXA:
            raise CaixaError("Forma de pagamento inválida.")
        valor = _moeda(_numero(pagamento.get("valor"), "o valor pago"))
        if valor <= 0:
            continue
        autorizacao = " ".join(str(pagamento.get("autorizacao") or "").split())[:40] or None
        pagos.append((t_pag, valor, autorizacao))
    if not pagos:
        raise CaixaError("Informe como o cliente pagou.")
    total_pago = sum((valor for _, valor, _ in pagos), ZERO)
    if total_pago < total:
        raise CaixaError(f"Faltam R$ {total - total_pago:.2f} para fechar a venda.".replace(".", ","))
    troco = total_pago - total
    dinheiro = sum((valor for t_pag, valor, _ in pagos if t_pag == "01"), ZERO)
    if troco > dinheiro:
        raise CaixaError("Só pagamento em dinheiro pode gerar troco.")

    venda = VendaBalcao(
        casa_de_racao_id=casa_id,
        chave_cliente=chave,
        sessao_id=sessao.id,
        status="concluida",
        subtotal=subtotal,
        desconto=desconto_total,
        total=total,
        troco=troco,
        emitir_nfce=bool(emitir_nfce),
        created_by_id=usuario_id,
        created_at=now_in_brazil(),
    )
    db.session.add(venda)
    for linha in linhas:
        product: Product = linha["product"]
        variant: Optional[ProductVariant] = linha["variant"]
        codigo_barras = (variant.barcode if variant is not None else None) or None
        csosn = (product.csosn or "").strip() or None
        venda.itens.append(
            VendaBalcaoItem(
                product_id=product.id,
                variant_id=variant.id if variant is not None else None,
                codigo=(variant.sku if variant is not None and variant.sku else None)
                or (f"P{product.id}V{variant.id}" if variant is not None else f"P{product.id}"),
                descricao=(
                    f"{product.name} {variant.name}"
                    if variant is not None and len(product.active_variants) > 1 and variant.name not in product.name
                    else product.name
                )[:160],
                unidade=unidade_de(product),
                quantidade=linha["quantidade"],
                preco_unitario=linha["preco"],
                desconto=linha["desconto"],
                total=linha["bruto"] - linha["desconto"],
                gtin=codigo_barras if gtin_valido(codigo_barras) else None,
                ncm=only_digits(product.ncm)[:8] or None,
                cest=only_digits(product.cest)[:7] or None,
                cfop=only_digits(product.cfop)[:4] or None,
                csosn=csosn[:3] if csosn else None,
                origem=(product.origem or "").strip()[:1] or None,
            )
        )
    for t_pag, valor, autorizacao in pagos:
        venda.pagamentos.append(VendaBalcaoPagamento(t_pag=t_pag, valor=valor, autorizacao=autorizacao))
    try:
        db.session.flush()
    except IntegrityError as exc:
        # Mesmo envio chegou duas vezes ao mesmo tempo: vale a venda já gravada.
        db.session.rollback()
        existente = venda_por_chave(casa_id, chave) if chave else None
        if existente is not None:
            raise VendaRepetida(existente) from exc
        raise CaixaError("Não foi possível gravar a venda. Tente de novo.") from exc
    try:
        for linha in linhas:
            estoque.movimentar(
                casa_de_racao_id=casa_id,
                product=linha["product"],
                variant=linha["variant"],
                quantidade=-linha["quantidade"],
                tipo="venda_balcao",
                referencia_tipo="venda",
                referencia_id=venda.id,
                usuario_id=usuario_id,
            )
    except EstoqueError as exc:
        db.session.rollback()
        raise CaixaError(str(exc)) from exc
    db.session.commit()
    return venda


# ------------------------------------------------------------------- NFC-e

def config_fiscal(casa_id: int) -> Optional[LojaFiscalConfig]:
    return LojaFiscalConfig.query.filter_by(casa_de_racao_id=casa_id).first()


def nfce_ligada(casa_id: int) -> bool:
    config = config_fiscal(casa_id)
    return bool(config and config.ativo and config.tem_certificado)


def itens_nfce(venda: VendaBalcao, config: LojaFiscalConfig) -> list[ItemNfce]:
    padrao = (config.csosn_padrao or "102").strip()
    itens = []
    for item in venda.itens:
        csosn = item.csosn if item.csosn in CSOSN_SN102 | CSOSN_SN500 else padrao
        # Dados fiscais atuais do produto valem se a venda foi gravada sem eles
        # (ex.: NCM preenchido depois de uma rejeição).
        product = item.product
        ncm = item.ncm or (only_digits(product.ncm)[:8] if product is not None else "")
        cest = item.cest or (only_digits(product.cest)[:7] if product is not None and product.cest else None)
        itens.append(
            ItemNfce(
                codigo=item.codigo,
                descricao=item.descricao,
                ncm=ncm or "",
                quantidade=Decimal(item.quantidade),
                valor_unitario=Decimal(item.preco_unitario),
                unidade=item.unidade or "UN",
                cfop=item.cfop or cfop_padrao(csosn),
                gtin=item.gtin,
                cest=cest or None,
                desconto=Decimal(item.desconto or 0),
                csosn=csosn,
                origem=item.origem or "0",
                pis_cst=config.pis_cst or "99",
                cofins_cst=config.cofins_cst or "99",
            )
        )
    return itens


def pagamentos_nfce(venda: VendaBalcao, config: LojaFiscalConfig) -> list[PagamentoNfce]:
    pagamentos = []
    for pagamento in venda.pagamentos:
        cartao = pagamento.t_pag in TPAG_COM_CARD
        pagamentos.append(
            PagamentoNfce(
                t_pag=pagamento.t_pag,
                valor=Decimal(pagamento.valor),
                tp_integra=(config.tp_integra or "2") if cartao else "2",
                cnpj_credenciadora=only_digits(config.credenciadora_cnpj) or None if cartao else None,
                autorizacao=pagamento.autorizacao if cartao else None,
                descricao="Outros" if pagamento.t_pag == "99" else None,
            )
        )
    return pagamentos


def emitir_nfce_venda(
    venda: VendaBalcao, *, cpf: str | None = None, usuario_id: int | None = None
) -> NfceDocumento:
    """Emite (ou reenvia) a NFC-e da venda. A venda nunca é desfeita aqui."""
    from services.loja_fiscal import nfce_service
    from services.loja_fiscal.nfce_service import NfceServiceError

    if venda.status != "concluida":
        raise CaixaError("Só vendas concluídas recebem NFC-e.")
    config = config_fiscal(venda.casa_de_racao_id)
    if config is None or not config.ativo:
        raise CaixaError("A emissão de NFC-e está desligada. Ligue em Notas fiscais (NFC-e).")
    cpf_digitos = only_digits(cpf)
    if cpf and len(cpf_digitos) != 11:
        raise CaixaError("CPF inválido.")

    documento = venda.nfce
    venda_id = venda.id
    if documento is not None and documento.status == "autorizada":
        raise CaixaError("Esta venda já tem NFC-e autorizada.")
    if documento is not None and documento.status == "denegada":
        raise CaixaError("A NFC-e desta venda foi denegada pela SEFAZ. Fale com o contador.")
    try:
        if documento is not None and documento.status in nfce_service.STATUS_REENVIAVEIS:
            documento = nfce_service.reenviar_nfce(
                documento,
                itens=itens_nfce(venda, config) if documento.status == "rejeitada" else None,
                pagamentos=pagamentos_nfce(venda, config) if documento.status == "rejeitada" else None,
            )
        else:
            # Sem nota, ou a anterior foi cancelada/inutilizada: nota nova.
            documento = nfce_service.emitir_nfce(
                config,
                itens=itens_nfce(venda, config),
                pagamentos=pagamentos_nfce(venda, config),
                cpf=cpf_digitos or None,
                origem="venda_balcao",
                origem_id=venda_id,
                usuario_id=usuario_id,
            )
    except NfceServiceError as exc:
        venda = db.session.get(VendaBalcao, venda_id)
        venda.nfce_erro = str(exc)[:255]
        db.session.commit()
        raise CaixaError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - venda já gravada; registra o aviso
        db.session.rollback()
        logger.exception("Falha ao emitir NFC-e da venda %s", venda_id)
        venda = db.session.get(VendaBalcao, venda_id)
        venda.nfce_erro = "Falha inesperada ao emitir a NFC-e. Tente de novo."
        db.session.commit()
        raise CaixaError(venda.nfce_erro) from exc

    venda = db.session.get(VendaBalcao, venda_id)
    venda.nfce_documento_id = documento.id
    if documento.status == "autorizada":
        venda.nfce_erro = None
    else:
        motivo = " · ".join(filter(None, [documento.c_stat, documento.x_motivo])) or documento.status_label
        venda.nfce_erro = f"NFC-e {documento.status_label.lower()}: {motivo}"[:255]
    db.session.commit()
    return documento


# ------------------------------------------------------------- cancelamento

def cancelar_venda(venda: VendaBalcao, *, motivo: str, usuario_id: int | None) -> VendaBalcao:
    """Cancela a NFC-e autorizada (se houver), devolve o estoque e marca a venda."""
    from services.loja_fiscal import nfce_service
    from services.loja_fiscal.nfce_service import NfceServiceError

    if venda.status != "concluida":
        raise CaixaError("Esta venda já foi cancelada.")
    justificativa = " ".join((motivo or "").split())
    if len(justificativa) < 15:
        raise CaixaError("Descreva o motivo do cancelamento com pelo menos 15 caracteres.")
    documento = venda.nfce
    if documento is not None:
        if documento.status == "autorizada":
            try:
                nfce_service.cancelar_nfce(documento, justificativa)
            except NfceServiceError as exc:
                raise CaixaError(str(exc)) from exc
        elif documento.status in {"pendente", "erro"}:
            raise CaixaError(
                "A NFC-e desta venda ainda não tem resposta da SEFAZ. Reenvie a nota "
                "para saber se foi autorizada antes de cancelar a venda."
            )

    venda = db.session.get(VendaBalcao, venda.id)
    for item in venda.itens:
        product = db.session.get(Product, item.product_id) if item.product_id else None
        if product is None:
            continue
        variant = db.session.get(ProductVariant, item.variant_id) if item.variant_id else None
        estoque.movimentar(
            casa_de_racao_id=venda.casa_de_racao_id,
            product=product,
            variant=variant,
            quantidade=Decimal(item.quantidade),
            tipo="cancelamento_venda",
            referencia_tipo="venda",
            referencia_id=venda.id,
            usuario_id=usuario_id,
        )
    venda.status = "cancelada"
    venda.cancel_motivo = justificativa[:255]
    venda.cancelada_em = now_in_brazil()
    db.session.commit()
    return venda
