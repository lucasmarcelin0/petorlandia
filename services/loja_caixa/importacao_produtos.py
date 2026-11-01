"""Importação do catálogo da loja por planilha (CSV), com prévia antes de gravar.

Serve para trazer os produtos de outro sistema (ex.: a Orlasoft): código de
barras, código interno, nome, preço, custo, unidade, estoque e dados fiscais.

- Produto novo entra fora da loja online (inativo), como na entrada por XML;
  o estoque inicial vira um movimento de inventário no histórico.
- Produto que já existe (achado pelo código de barras, pelo código interno ou
  pelo nome) só ganha os dados que faltam. Preço e estoque dele só mudam se a
  loja marcar essas opções na prévia.
- Nada é apagado e nenhuma linha com erro é gravada.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal
import io
import re
import unicodedata
from typing import Any, Optional

from extensions import db
from models import CasaDeRacao, Product, ProductVariant
from models.loja_caixa import UNIDADES_FRACIONADAS
from providers.nfe.chave import only_digits
from services.loja_caixa import estoque
from services.loja_caixa.entrada import UNIDADES_VENDA
from services.loja_caixa.estoque import EstoqueError

MAX_BYTES = 2 * 1024 * 1024
MAX_LINHAS = 5000
OBSERVACAO = "Importação da planilha"
CSOSN_VALIDOS = {"101", "102", "103", "201", "202", "203", "300", "400", "500", "900"}

COLUNAS: dict[str, tuple[str, ...]] = {
    "codigo_barras": (
        "codigo barras", "codigo de barras", "cod barras", "barras", "ean", "gtin", "codigo ean", "cod ean",
    ),
    "codigo": ("codigo", "cod", "codigo interno", "cod interno", "referencia", "ref", "sku"),
    "nome": ("nome", "produto", "descricao", "descricao do produto", "nome do produto"),
    "preco": (
        "preco", "preco venda", "preco de venda", "valor", "valor venda", "valor de venda", "venda", "pv",
    ),
    "custo": ("custo", "preco custo", "preco de custo", "custo unitario", "valor custo", "valor de custo"),
    "unidade": ("unidade", "un", "und", "unid", "medida", "unidade de medida"),
    "estoque": ("estoque", "estoque atual", "saldo", "quantidade", "qtd", "qtde", "quant"),
    "ncm": ("ncm",),
    "cest": ("cest",),
    "cfop": ("cfop",),
    "csosn": ("csosn", "cst/csosn", "cst csosn"),
    "origem": ("origem", "origem da mercadoria"),
}

MODELO_CABECALHO = [
    "codigo_barras", "codigo", "nome", "preco", "custo", "unidade", "estoque",
    "ncm", "cest", "cfop", "csosn", "origem",
]
MODELO_EXEMPLOS = [
    ["7891000315507", "RAC15", "Ração Premium Adulto 15 kg", "189,90", "120,00", "UN", "8",
     "23091000", "", "5102", "102", "0"],
    ["", "GRANEL-GATO", "Ração a granel para gatos", "18,50", "11,20", "KG", "12,5",
     "23091000", "", "5102", "102", "0"],
]

_UNIDADES_SINONIMAS = {
    "UND": "UN", "UNID": "UN", "UNIDADE": "UN", "PC": "UN", "PÇ": "UN", "PECA": "UN", "PEÇA": "UN",
    "KILO": "KG", "QUILO": "KG", "KGS": "KG", "LT": "L", "LITRO": "L", "PACOTE": "PCT", "CAIXA": "CX",
    "SACO": "SC", "FARDO": "FD",
}


class PlanilhaInvalida(ValueError):
    """Arquivo que não dá para ler como planilha de produtos."""


def _chave(texto) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9/]+", " ", texto).split())


_ALIASES = {canonica: {_chave(a) for a in aceitos} for canonica, aceitos in COLUNAS.items()}


def gerar_modelo_csv() -> str:
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";")
    escritor.writerow(MODELO_CABECALHO)
    escritor.writerows(MODELO_EXEMPLOS)
    return saida.getvalue()


def ler_planilha(conteudo: bytes) -> list[dict[str, str]]:
    """Lê o CSV (vírgula ou ponto e vírgula; UTF-8 ou Latin-1) em linhas com as colunas canônicas."""
    if not conteudo or not conteudo.strip():
        raise PlanilhaInvalida("O arquivo está vazio.")
    if len(conteudo) > MAX_BYTES:
        raise PlanilhaInvalida("Arquivo grande demais (máximo de 2 MB). Divida a planilha em partes.")
    if conteudo[:4] == b"PK\x03\x04":
        raise PlanilhaInvalida(
            'Este arquivo é do Excel (.xlsx). No Excel, use Arquivo > Salvar como > '
            '"CSV (separado por vírgulas)" e envie o arquivo .csv.'
        )
    texto = None
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            texto = conteudo.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise PlanilhaInvalida("Não foi possível ler o texto do arquivo. Salve a planilha como CSV.")
    primeira = texto.splitlines()[0] if texto.splitlines() else ""
    delimitador = ";" if primeira.count(";") >= primeira.count(",") else ","
    leitor = csv.reader(io.StringIO(texto), delimiter=delimitador)
    cabecalho = next(leitor, None) or []

    mapa: dict[str, int] = {}
    for indice, nome in enumerate(cabecalho):
        chave = _chave(nome)
        for canonica, aceitos in _ALIASES.items():
            if canonica not in mapa and chave in aceitos:
                mapa[canonica] = indice
                break
    if "nome" not in mapa:
        raise PlanilhaInvalida(
            "Não achamos a coluna com o nome do produto. A primeira linha precisa ter os títulos "
            "das colunas, como no modelo (ex.: codigo_barras, nome, preco, estoque)."
        )

    linhas = []
    for numero, valores in enumerate(leitor, start=2):
        if not any((v or "").strip() for v in valores):
            continue
        linha = {
            canonica: (valores[indice].strip() if indice < len(valores) else "")
            for canonica, indice in mapa.items()
        }
        linha["linha"] = str(numero)
        linhas.append(linha)
        if len(linhas) > MAX_LINHAS:
            raise PlanilhaInvalida(f"A planilha passa de {MAX_LINHAS} produtos. Divida em partes menores.")
    if not linhas:
        raise PlanilhaInvalida("A planilha não tem linhas preenchidas abaixo do cabeçalho.")
    return linhas


# ------------------------------------------------------------------ prévia

@dataclass
class LinhaPlano:
    numero: int
    nome: str
    acao: str = "criar"  # criar | atualizar | nada | erro
    codigo_barras: Optional[str] = None
    codigo: Optional[str] = None
    preco: Optional[Decimal] = None
    custo: Optional[Decimal] = None
    unidade: Optional[str] = None
    estoque: Optional[Decimal] = None
    fiscal: dict[str, str] = field(default_factory=dict)
    product: Optional[Product] = None
    variant: Optional[ProductVariant] = None
    mudancas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)

    @property
    def existente(self) -> str:
        return self.product.name if self.product is not None else ""


def _numero(texto: str, rotulo: str, linha: LinhaPlano, *, obrigatorio: bool = False) -> Optional[Decimal]:
    if not (texto or "").strip():
        if obrigatorio:
            linha.erros.append(f"sem {rotulo}")
        return None
    try:
        valor = estoque.decimal_de(texto, rotulo)
    except EstoqueError:
        linha.erros.append(f"{rotulo} ilegível ({texto})")
        return None
    return valor


def _codigo_barras(texto: str, linha: LinhaPlano) -> Optional[str]:
    bruto = (texto or "").strip()
    if not bruto:
        return None
    if re.search(r"[eE][+-]?\d", bruto):
        linha.avisos.append("código de barras em notação científica do Excel: ignorado")
        return None
    digitos = only_digits(re.sub(r"[.,]0+$", "", bruto))
    if not 6 <= len(digitos) <= 14:
        linha.avisos.append(f"código de barras inválido ({bruto}): ignorado")
        return None
    return digitos


def _unidade(texto: str, linha: LinhaPlano) -> Optional[str]:
    bruto = (texto or "").strip().upper()
    if not bruto:
        return None
    unidade = _UNIDADES_SINONIMAS.get(bruto, bruto)
    if unidade not in UNIDADES_VENDA:
        linha.avisos.append(f"unidade {bruto} não reconhecida: fica UN")
        return None
    return unidade


def _fiscal(dados: dict[str, str], linha: LinhaPlano) -> dict[str, str]:
    regras = {"ncm": (8, 8), "cest": (7, 7), "cfop": (4, 4), "csosn": (3, 3), "origem": (1, 1)}
    resultado = {}
    for campo, (minimo, maximo) in regras.items():
        bruto = (dados.get(campo) or "").strip()
        if not bruto:
            continue
        valor = only_digits(bruto)
        valido = minimo <= len(valor) <= maximo
        if campo == "csosn" and valor not in CSOSN_VALIDOS:
            valido = False
        if campo == "origem" and valor not in set("012345678"):
            valido = False
        if valido:
            resultado[campo] = valor
        else:
            linha.avisos.append(f"{campo.upper()} inválido ({bruto}): ignorado")
    return resultado


def _reais(valor) -> str:
    return f"{Decimal(str(valor)):.2f}".replace(".", ",")


def _nome_normalizado(nome: str) -> str:
    return _chave(nome)


def _variante_unica(product: Product) -> Optional[ProductVariant]:
    variantes = [v for v in product.variants if v.status == "active"] or list(product.variants)
    return variantes[0] if len(variantes) == 1 else None


def planejar(
    casa_id: int,
    linhas: list[dict[str, Any]],
    *,
    atualizar_precos: bool = False,
    ajustar_estoque: bool = False,
) -> list[LinhaPlano]:
    """O que cada linha vai fazer, sem gravar nada."""
    produtos = Product.query.filter(Product.casa_de_racao_id == casa_id).all()
    por_barras: dict[str, ProductVariant] = {}
    por_codigo: dict[str, ProductVariant] = {}
    por_nome: dict[str, list[Product]] = {}
    for product in produtos:
        por_nome.setdefault(_nome_normalizado(product.name), []).append(product)
        for variant in product.variants:
            if variant.barcode:
                por_barras.setdefault(variant.barcode.strip(), variant)
            if variant.sku:
                por_codigo.setdefault(variant.sku.strip().lower(), variant)

    vistos: dict[str, int] = {}
    plano: list[LinhaPlano] = []
    for dados in linhas:
        numero = int(dados.get("linha") or len(plano) + 2)
        nome = " ".join((dados.get("nome") or "").split())[:120]
        linha = LinhaPlano(numero=numero, nome=nome)
        if not nome:
            linha.erros.append("sem nome")
        linha.codigo_barras = _codigo_barras(dados.get("codigo_barras", ""), linha)
        codigo = " ".join((dados.get("codigo") or "").split())[:60]
        linha.codigo = codigo or None
        linha.preco = _numero(dados.get("preco", ""), "preço", linha)
        if linha.preco is not None and linha.preco <= 0:
            linha.erros.append("preço precisa ser maior que zero")
        custo = _numero(dados.get("custo", ""), "custo", linha)
        if custo is not None and custo < 0:
            linha.avisos.append("custo negativo: ignorado")
            custo = None
        linha.custo = custo
        linha.unidade = _unidade(dados.get("unidade", ""), linha)
        quantidade = _numero(dados.get("estoque", ""), "estoque", linha)
        if quantidade is not None and quantidade < 0:
            linha.avisos.append("estoque negativo: fica zero")
            quantidade = Decimal("0")
        linha.estoque = quantidade
        linha.fiscal = _fiscal(dados, linha)

        # Repetidos na própria planilha: só a primeira linha vale.
        for chave in filter(None, [
            f"barras:{linha.codigo_barras}" if linha.codigo_barras else None,
            f"codigo:{linha.codigo.lower()}" if linha.codigo else None,
            f"nome:{_nome_normalizado(nome)}" if nome and not (linha.codigo_barras or linha.codigo) else None,
        ]):
            if chave in vistos:
                linha.erros.append(f"repetido na planilha (linha {vistos[chave]})")
                break
            vistos[chave] = numero

        # Produto que já existe na loja.
        variant = por_barras.get(linha.codigo_barras or "") or por_codigo.get((linha.codigo or "").lower())
        if variant is not None:
            linha.product, linha.variant = variant.product, variant
        elif nome:
            mesmos = por_nome.get(_nome_normalizado(nome), [])
            if len(mesmos) > 1:
                linha.erros.append("há mais de um produto com este nome na loja: informe o código de barras")
            elif mesmos:
                linha.product = mesmos[0]
                linha.variant = _variante_unica(mesmos[0])

        if linha.erros:
            linha.acao = "erro"
        elif linha.product is None:
            if linha.preco is None:
                linha.erros.append("sem preço")
                linha.acao = "erro"
            else:
                linha.acao = "criar"
                if linha.estoque is not None:
                    _quantidade_valida((linha.unidade or "UN") in UNIDADES_FRACIONADAS, linha)  # avisa já na prévia
        else:
            linha.mudancas = _mudancas(linha, atualizar_precos=atualizar_precos, ajustar_estoque=ajustar_estoque)
            linha.acao = "atualizar" if linha.mudancas else "nada"
        plano.append(linha)
    return plano


def _mudancas(linha: LinhaPlano, *, atualizar_precos: bool, ajustar_estoque: bool) -> list[str]:
    """Para produto existente: só preenche o que falta; preço e estoque, se a loja pedir."""
    product, variant = linha.product, linha.variant
    mudancas = []
    for campo, valor in linha.fiscal.items():
        if not (getattr(product, campo) or "").strip():
            mudancas.append(f"{campo.upper()} {valor}")
    if linha.unidade and not (product.unidade or "").strip():
        mudancas.append(f"unidade {linha.unidade}")
    if variant is not None:
        if linha.codigo_barras and not variant.barcode:
            mudancas.append(f"código de barras {linha.codigo_barras}")
        if linha.codigo and not variant.sku:
            mudancas.append(f"código {linha.codigo}")
        if linha.custo is not None and variant.custo is None:
            mudancas.append(f"custo {_reais(linha.custo)}")
        if atualizar_precos and linha.preco is not None and Decimal(str(variant.price)) != linha.preco:
            mudancas.append(f"preço {_reais(variant.price)} → {_reais(linha.preco)}")
        if ajustar_estoque and linha.estoque is not None:
            atual = estoque.saldo(product, variant)
            novo = _quantidade_valida(estoque.fracionado(product), linha)
            if novo != atual:
                unidade = estoque.unidade_de(product)
                mudancas.append(
                    f"estoque {estoque.formatar_quantidade(atual, unidade)} → {estoque.formatar_quantidade(novo, unidade)}"
                )
    elif atualizar_precos or ajustar_estoque:
        linha.avisos.append("produto com várias apresentações: preço e estoque só pelo código de barras")
    return mudancas


def _quantidade_valida(fracionado: bool, linha: LinhaPlano) -> Decimal:
    """Unidade inteira não guarda fração: arredonda para baixo (com aviso)."""
    quantidade = linha.estoque or Decimal("0")
    if not fracionado and quantidade != quantidade.to_integral_value():
        quantidade = quantidade.to_integral_value(rounding=ROUND_FLOOR)
        aviso = "estoque com fração em produto vendido por unidade: arredondado para baixo"
        if aviso not in linha.avisos:
            linha.avisos.append(aviso)
    return quantidade


def resumo(plano: list[LinhaPlano]) -> dict[str, int]:
    totais = {"linhas": len(plano), "criar": 0, "atualizar": 0, "nada": 0, "erro": 0}
    for linha in plano:
        totais[linha.acao] += 1
    return totais


# --------------------------------------------------------------- gravação

def aplicar(
    casa: CasaDeRacao,
    linhas: list[dict[str, Any]],
    *,
    atualizar_precos: bool = False,
    ajustar_estoque: bool = False,
    usuario_id: int | None = None,
) -> dict[str, int]:
    """Grava a prévia (recalculada agora). Tudo ou nada."""
    plano = planejar(casa.id, linhas, atualizar_precos=atualizar_precos, ajustar_estoque=ajustar_estoque)
    existentes = [linha for linha in plano if linha.acao == "atualizar"]
    estoque.travar_saldos(
        (linha.product.id for linha in existentes),
        (linha.variant.id for linha in existentes if linha.variant is not None),
    )
    totais = {"criados": 0, "atualizados": 0, "sem_mudanca": 0, "com_erro": 0, "com_estoque": 0}
    try:
        for linha in plano:
            if linha.acao == "erro":
                totais["com_erro"] += 1
            elif linha.acao == "nada":
                totais["sem_mudanca"] += 1
            elif linha.acao == "criar":
                if _criar(casa, linha, usuario_id):
                    totais["com_estoque"] += 1
                totais["criados"] += 1
            else:
                if _atualizar(casa, linha, atualizar_precos, ajustar_estoque, usuario_id):
                    totais["com_estoque"] += 1
                totais["atualizados"] += 1
    except Exception:
        db.session.rollback()
        raise
    db.session.commit()
    return totais


def _criar(casa: CasaDeRacao, linha: LinhaPlano, usuario_id: int | None) -> bool:
    preco = float(linha.preco)
    product = Product(
        casa_de_racao_id=casa.id,
        name=linha.nome,
        price=preco,
        stock=0,
        status="inactive",  # fora da loja online até a loja publicar
        unidade=linha.unidade or "UN",
        **linha.fiscal,
    )
    variant = ProductVariant(
        name="Padrão",
        price=preco,
        stock=0,
        status="active",
        position=0,
        barcode=linha.codigo_barras,
        sku=linha.codigo,
        custo=linha.custo,
    )
    product.variants.append(variant)
    db.session.add(product)
    db.session.flush()
    quantidade = _quantidade_valida(estoque.fracionado(product), linha)
    if quantidade > 0:
        estoque.movimentar(
            casa_de_racao_id=casa.id,
            product=product,
            variant=variant,
            quantidade=quantidade,
            tipo="inventario",
            usuario_id=usuario_id,
            custo_unitario=linha.custo,
            observacao=OBSERVACAO,
        )
        return True
    return False


def _atualizar(
    casa: CasaDeRacao, linha: LinhaPlano, atualizar_precos: bool, ajustar_estoque: bool, usuario_id: int | None
) -> bool:
    product, variant = linha.product, linha.variant
    for campo, valor in linha.fiscal.items():
        if not (getattr(product, campo) or "").strip():
            setattr(product, campo, valor)
    if linha.unidade and not (product.unidade or "").strip():
        product.unidade = linha.unidade
    if variant is None:
        return False
    if linha.codigo_barras and not variant.barcode:
        variant.barcode = linha.codigo_barras
    if linha.codigo and not variant.sku:
        variant.sku = linha.codigo
    if linha.custo is not None and variant.custo is None:
        variant.custo = linha.custo
    if atualizar_precos and linha.preco is not None:
        variant.price = float(linha.preco)
        if _variante_unica(product) is variant:
            product.price = float(linha.preco)
    if ajustar_estoque and linha.estoque is not None:
        movimento = estoque.ajustar_para(
            casa_de_racao_id=casa.id,
            product=product,
            variant=variant,
            novo_saldo=_quantidade_valida(estoque.fracionado(product), linha),
            tipo="inventario",
            usuario_id=usuario_id,
            observacao=OBSERVACAO,
        )
        return movimento is not None
    return False
