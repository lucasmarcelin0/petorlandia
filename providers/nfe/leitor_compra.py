"""Leitura do XML de uma NF-e de compra (modelo 55) recebida de fornecedor.

Aceita o ``nfeProc`` (nota + protocolo, o arquivo que o fornecedor envia)
ou só a ``NFe``. O XML vem de fora: é lido com o parser protegido.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

from providers.nfe.chave import only_digits
from security.xml_safe import safe_lxml_fromstring


NFE_NS = "http://www.portalfiscal.inf.br/nfe"
_NS = {"n": NFE_NS}
ZERO = Decimal("0")
CSTAT_AUTORIZADA = {"100", "150"}


class NotaCompraInvalida(ValueError):
    """O arquivo não é uma NF-e legível; a mensagem vai para a tela."""


def _dec(texto: Optional[str]) -> Decimal:
    if not texto:
        return ZERO
    try:
        return Decimal(texto.strip())
    except InvalidOperation:
        return ZERO


def gtin_ou_none(codigo: Optional[str]) -> Optional[str]:
    """GTIN de circulação (8/12/13/14 dígitos, DV certo); "SEM GTIN" vira None."""
    from providers.nfce.xml_builder import gtin_valido

    codigo = (codigo or "").strip()
    return codigo if gtin_valido(codigo) else None


@dataclass
class ItemCompra:
    n_item: int
    codigo: str
    descricao: str
    unidade: str
    quantidade: Decimal
    valor_unitario: Decimal
    valor_produtos: Decimal
    gtin: Optional[str] = None
    gtin_trib: Optional[str] = None
    unidade_trib: Optional[str] = None
    quantidade_trib: Optional[Decimal] = None
    ncm: Optional[str] = None
    cest: Optional[str] = None
    cfop: Optional[str] = None
    origem: Optional[str] = None
    desconto: Decimal = ZERO
    frete: Decimal = ZERO
    seguro: Decimal = ZERO
    outros: Decimal = ZERO
    icms_st: Decimal = ZERO
    ipi: Decimal = ZERO

    @property
    def custo_total(self) -> Decimal:
        """Custo de aquisição do item: produtos − desconto + despesas + ST + IPI."""
        return (
            self.valor_produtos - self.desconto + self.frete + self.seguro + self.outros + self.icms_st + self.ipi
        ).quantize(Decimal("0.01"))

    @property
    def fator_sugerido(self) -> Decimal:
        """Unidades de venda por unidade de compra (ex.: caixa com 12).

        Vem da unidade tributável quando ela difere da comercial e a razão
        é inteira (ex.: 2 CX = 24 UN → 12).
        """
        if (
            self.unidade_trib
            and self.unidade_trib.upper() != (self.unidade or "").upper()
            and self.quantidade_trib
            and self.quantidade > 0
        ):
            razao = self.quantidade_trib / self.quantidade
            if razao > 1 and razao == razao.to_integral_value():
                return razao.quantize(Decimal("1"))
        return Decimal("1")


@dataclass
class NotaCompra:
    chave: str
    numero: str
    serie: str
    modelo: str
    dh_emi: Optional[str]
    fornecedor_cnpj: str
    fornecedor_nome: str
    destinatario_documento: str
    valor_total: Decimal
    protocolo: Optional[str] = None
    autorizada: bool = False
    itens: list[ItemCompra] = field(default_factory=list)


def _texto(no, caminho: str) -> Optional[str]:
    if no is None:
        return None
    alvo = no.find(caminho, _NS)
    if alvo is None or alvo.text is None:
        return None
    return alvo.text.strip() or None


def _soma_impostos(det) -> tuple[Decimal, Decimal, Optional[str]]:
    """ICMS-ST + FCP-ST, IPI e a origem da mercadoria do item."""
    imposto = det.find("n:imposto", _NS)
    st = ZERO
    origem = None
    if imposto is not None:
        icms = imposto.find("n:ICMS", _NS)
        if icms is not None and len(icms):
            grupo = icms[0]
            origem = _texto(grupo, "n:orig")
            st = _dec(_texto(grupo, "n:vICMSST")) + _dec(_texto(grupo, "n:vFCPST"))
        ipi = _dec(_texto(imposto, "n:IPI/n:IPITrib/n:vIPI"))
    else:
        ipi = ZERO
    return st, ipi, origem


def ler_nota_compra(conteudo: bytes | str) -> NotaCompra:
    if isinstance(conteudo, str):
        conteudo = conteudo.encode("utf-8")
    conteudo = (conteudo or b"").strip()
    if conteudo.startswith(b"\xef\xbb\xbf"):
        conteudo = conteudo[3:]
    if not conteudo.startswith(b"<"):
        raise NotaCompraInvalida("O arquivo não é um XML.")
    try:
        root = safe_lxml_fromstring(conteudo)
    except Exception as exc:  # noqa: BLE001 - XML malformado ou com DOCTYPE
        raise NotaCompraInvalida("Não foi possível ler o XML da nota.") from exc

    inf = root.find(".//n:NFe/n:infNFe", _NS)
    if inf is None and root.tag == f"{{{NFE_NS}}}NFe":
        inf = root.find("n:infNFe", _NS)
    if inf is None:
        raise NotaCompraInvalida("O arquivo não é uma NF-e (procure o XML da nota, não o DANFE).")

    ide = inf.find("n:ide", _NS)
    modelo = _texto(ide, "n:mod") or ""
    if modelo != "55":
        raise NotaCompraInvalida("Só notas de compra modelo 55 (NF-e) entram no estoque.")
    chave = only_digits(inf.get("Id"))
    if len(chave) != 44:
        raise NotaCompraInvalida("A nota não tem chave de acesso válida.")

    emit = inf.find("n:emit", _NS)
    dest = inf.find("n:dest", _NS)
    prot = root.find(".//n:protNFe/n:infProt", _NS)
    c_stat = _texto(prot, "n:cStat")

    nota = NotaCompra(
        chave=chave,
        numero=_texto(ide, "n:nNF") or "",
        serie=_texto(ide, "n:serie") or "",
        modelo=modelo,
        dh_emi=_texto(ide, "n:dhEmi") or _texto(ide, "n:dEmi"),
        fornecedor_cnpj=only_digits(_texto(emit, "n:CNPJ") or _texto(emit, "n:CPF")),
        fornecedor_nome=(_texto(emit, "n:xFant") or _texto(emit, "n:xNome") or "Fornecedor")[:160],
        destinatario_documento=only_digits(_texto(dest, "n:CNPJ") or _texto(dest, "n:CPF")),
        valor_total=_dec(_texto(inf, "n:total/n:ICMSTot/n:vNF")),
        protocolo=_texto(prot, "n:nProt"),
        autorizada=c_stat in CSTAT_AUTORIZADA,
    )

    for det in inf.findall("n:det", _NS):
        prod = det.find("n:prod", _NS)
        if prod is None:
            continue
        st, ipi, origem = _soma_impostos(det)
        quantidade_trib = _texto(prod, "n:qTrib")
        nota.itens.append(
            ItemCompra(
                n_item=int(det.get("nItem") or len(nota.itens) + 1),
                codigo=(_texto(prod, "n:cProd") or "")[:60],
                descricao=" ".join((_texto(prod, "n:xProd") or "Produto").split())[:160],
                unidade=(_texto(prod, "n:uCom") or "UN").upper()[:6],
                quantidade=_dec(_texto(prod, "n:qCom")),
                valor_unitario=_dec(_texto(prod, "n:vUnCom")),
                valor_produtos=_dec(_texto(prod, "n:vProd")),
                gtin=gtin_ou_none(_texto(prod, "n:cEAN")),
                gtin_trib=gtin_ou_none(_texto(prod, "n:cEANTrib")),
                unidade_trib=((_texto(prod, "n:uTrib") or "").upper()[:6] or None),
                quantidade_trib=_dec(quantidade_trib) if quantidade_trib else None,
                ncm=only_digits(_texto(prod, "n:NCM"))[:8] or None,
                cest=only_digits(_texto(prod, "n:CEST"))[:7] or None,
                cfop=only_digits(_texto(prod, "n:CFOP"))[:4] or None,
                origem=origem,
                desconto=_dec(_texto(prod, "n:vDesc")),
                frete=_dec(_texto(prod, "n:vFrete")),
                seguro=_dec(_texto(prod, "n:vSeg")),
                outros=_dec(_texto(prod, "n:vOutro")),
                icms_st=st,
                ipi=ipi,
            )
        )
    if not nota.itens:
        raise NotaCompraInvalida("A nota não tem itens.")
    return nota
