"""XML da NFC-e (modelo 65, leiaute 4.00) para varejo do Simples Nacional.

A ordem dos elementos segue o ``leiauteNFe_v4.00.xsd`` vigente (com os
grupos da reforma tributária) e é conferida nos testes contra o esquema
oficial. Regras de validação da SEFAZ cobertas aqui:

- homologação: a descrição do 1º item e o nome do consumidor viram o texto
  "... EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL" (rejeição 373);
- vProd = qCom × vUnCom arredondado a 2 casas (rejeição 629);
- totais iguais à soma dos itens; Simples Nacional sem base de ICMS;
- troco = soma dos pagamentos − vNF;
- cartão/PIX dinâmico com o grupo ``card`` (rejeição 391);
- GTIN só quando válido; códigos internos vão como "SEM GTIN".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from lxml import etree

from providers.nfe.chave import ChaveAcesso, only_digits


NFE_NS = "http://www.portalfiscal.inf.br/nfe"
SEM_GTIN = "SEM GTIN"
HOMOLOG_ITEM = "NOTA FISCAL EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"
HOMOLOG_DEST = "NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"
CENT = Decimal("0.01")

# CSOSN do Simples Nacional sem destaque de ICMS na venda ao consumidor.
CSOSN_SN102 = {"102", "103", "300", "400"}
CSOSN_SN500 = {"500"}
# CST de PIS/COFINS no grupo "Outras operações" e no grupo "Não tributado".
CST_OUTR = {"49", "50", "51", "52", "53", "54", "55", "56", "60", "61", "62", "63", "64", "65", "66", "67", "70", "71", "72", "73", "74", "75", "98", "99"}
CST_NT = {"04", "05", "06", "07", "08", "09"}
# Formas de pagamento que exigem o grupo de cartão/pagamento eletrônico.
TPAG_COM_CARD = {"03", "04", "17"}

FORMAS_PAGAMENTO = {
    "01": "Dinheiro",
    "03": "Cartão de crédito",
    "04": "Cartão de débito",
    "05": "Crédito loja",
    "17": "PIX dinâmico",
    "20": "PIX estático",
    "99": "Outros",
}


class NfceValidationError(ValueError):
    """Dado da venda que a SEFAZ recusaria; a mensagem vai para a tela."""


@dataclass
class EmitenteNfce:
    cnpj: str
    razao_social: str
    ie: str
    logradouro: str
    numero: str
    bairro: str
    codigo_municipio: str
    municipio: str
    uf: str = "SP"
    cep: Optional[str] = None
    complemento: Optional[str] = None
    telefone: Optional[str] = None
    nome_fantasia: Optional[str] = None
    crt: str = "1"


@dataclass
class ItemNfce:
    codigo: str
    descricao: str
    ncm: str
    quantidade: Decimal
    valor_unitario: Decimal
    unidade: str = "UN"
    cfop: Optional[str] = None
    gtin: Optional[str] = None
    cest: Optional[str] = None
    desconto: Decimal = Decimal("0")
    csosn: str = "102"
    origem: str = "0"
    pis_cst: str = "99"
    cofins_cst: str = "99"

    @property
    def valor_bruto(self) -> Decimal:
        return (Decimal(self.quantidade) * Decimal(self.valor_unitario)).quantize(CENT, ROUND_HALF_UP)

    @property
    def valor_desconto(self) -> Decimal:
        return Decimal(self.desconto or 0).quantize(CENT, ROUND_HALF_UP)

    @property
    def valor_liquido(self) -> Decimal:
        return self.valor_bruto - self.valor_desconto


@dataclass
class PagamentoNfce:
    t_pag: str
    valor: Decimal
    tp_integra: str = "2"
    cnpj_credenciadora: Optional[str] = None
    bandeira: Optional[str] = None
    autorizacao: Optional[str] = None
    descricao: Optional[str] = None


@dataclass
class NfceDados:
    emitente: EmitenteNfce
    itens: list[ItemNfce]
    pagamentos: list[PagamentoNfce]
    chave: ChaveAcesso
    serie: int
    numero: int
    dh_emi: str
    tp_amb: str
    tp_emis: str = "1"
    dh_cont: Optional[str] = None
    x_just: Optional[str] = None
    cpf_consumidor: Optional[str] = None
    nome_consumidor: Optional[str] = None
    inf_cpl: Optional[str] = None
    percentual_tributos: Optional[Decimal] = None
    ver_proc: str = "PetOrlandia 1.0"
    nat_op: str = "VENDA"
    extras: dict = field(default_factory=dict)

    @property
    def total_produtos(self) -> Decimal:
        return sum((item.valor_bruto for item in self.itens), Decimal("0"))

    @property
    def total_desconto(self) -> Decimal:
        return sum((item.valor_desconto for item in self.itens), Decimal("0"))

    @property
    def total_nota(self) -> Decimal:
        return self.total_produtos - self.total_desconto

    @property
    def total_pago(self) -> Decimal:
        return sum((Decimal(p.valor) for p in self.pagamentos), Decimal("0")).quantize(CENT, ROUND_HALF_UP)

    @property
    def troco(self) -> Decimal:
        return max(self.total_pago - self.total_nota, Decimal("0"))

    @property
    def tributos_aproximados(self) -> Optional[Decimal]:
        if not self.percentual_tributos:
            return None
        return (self.total_nota * Decimal(self.percentual_tributos) / Decimal("100")).quantize(CENT, ROUND_HALF_UP)


def gtin_valido(codigo: str | None) -> bool:
    """GTIN-8/12/13/14 com dígito verificador correto e de circulação geral."""
    digits = only_digits(codigo)
    if not codigo or digits != str(codigo).strip() or len(digits) not in (8, 12, 13, 14):
        return False
    if len(digits) == 13 and digits.startswith("2"):
        return False  # prefixo 2: uso interno/restrito, fora do cadastro GS1
    total = 0
    for index, char in enumerate(reversed(digits[:-1])):
        total += int(char) * (3 if index % 2 == 0 else 1)
    return (10 - total % 10) % 10 == int(digits[-1])


def cfop_padrao(csosn: str) -> str:
    """5405 para mercadoria com ICMS retido por substituição; 5102 nos demais."""
    return "5405" if csosn in CSOSN_SN500 else "5102"


def _fmt2(value: Decimal) -> str:
    return f"{Decimal(value).quantize(CENT, ROUND_HALF_UP):.2f}"


def _fmt_qtd(value: Decimal) -> str:
    return f"{Decimal(value).quantize(Decimal('0.0001'), ROUND_HALF_UP):.4f}"


def _fmt_unit(value: Decimal) -> str:
    quantized = Decimal(value).quantize(Decimal("0.0000000001"), ROUND_HALF_UP).normalize()
    exponent = -quantized.as_tuple().exponent if quantized.as_tuple().exponent < 0 else 0
    return f"{quantized:.{max(2, exponent)}f}"


def _sub(parent: etree._Element, tag: str, text: object | None = None) -> etree._Element:
    element = etree.SubElement(parent, tag)
    if text is not None:
        element.text = str(text)
    return element


def _limpar(texto: str | None, limite: int) -> str:
    return " ".join(str(texto or "").split())[:limite]


def validar_dados(dados: NfceDados) -> None:
    if not dados.itens:
        raise NfceValidationError("A venda não tem itens.")
    if len(dados.itens) > 990:
        raise NfceValidationError("A NFC-e aceita no máximo 990 itens.")
    for item in dados.itens:
        nome = item.descricao or item.codigo
        ncm = only_digits(item.ncm)
        if len(ncm) != 8:
            raise NfceValidationError(f"O produto \"{nome}\" está sem NCM válido (8 dígitos).")
        if Decimal(item.quantidade) <= 0:
            raise NfceValidationError(f"Quantidade inválida no produto \"{nome}\".")
        if Decimal(item.valor_unitario) <= 0:
            raise NfceValidationError(f"Preço inválido no produto \"{nome}\".")
        if item.valor_desconto < 0 or item.valor_desconto >= item.valor_bruto:
            raise NfceValidationError(f"Desconto inválido no produto \"{nome}\".")
        if item.csosn not in CSOSN_SN102 | CSOSN_SN500:
            raise NfceValidationError(f"CSOSN {item.csosn} não suportado no produto \"{nome}\".")
    if dados.total_nota <= 0:
        raise NfceValidationError("O total da venda precisa ser maior que zero.")
    if not dados.pagamentos:
        raise NfceValidationError("Informe a forma de pagamento.")
    if dados.total_pago < dados.total_nota:
        raise NfceValidationError("O valor pago é menor que o total da venda.")
    troco_permitido = sum(
        (Decimal(p.valor) for p in dados.pagamentos if p.t_pag == "01"), Decimal("0")
    )
    if dados.troco > troco_permitido:
        raise NfceValidationError("Só pagamento em dinheiro pode gerar troco.")
    cpf = only_digits(dados.cpf_consumidor)
    if dados.cpf_consumidor and len(cpf) != 11:
        raise NfceValidationError("CPF do consumidor inválido.")


def build_nfce_xml(dados: NfceDados, *, qrcode: str, url_chave: str) -> str:
    """Monta ``<NFe>`` (sem assinatura) com ``infNFe`` e ``infNFeSupl``."""
    validar_dados(dados)
    homologacao = dados.tp_amb == "2"
    nfe = etree.Element("NFe", nsmap={None: NFE_NS})
    inf = etree.SubElement(nfe, "infNFe", Id=f"NFe{dados.chave.chave}", versao="4.00")

    ide = _sub(inf, "ide")
    _sub(ide, "cUF", dados.chave.chave[:2])
    _sub(ide, "cNF", dados.chave.c_nf)
    _sub(ide, "natOp", _limpar(dados.nat_op, 60))
    _sub(ide, "mod", "65")
    _sub(ide, "serie", int(dados.serie))
    _sub(ide, "nNF", int(dados.numero))
    _sub(ide, "dhEmi", dados.dh_emi)
    _sub(ide, "tpNF", "1")
    _sub(ide, "idDest", "1")
    _sub(ide, "cMunFG", only_digits(dados.emitente.codigo_municipio))
    _sub(ide, "tpImp", "4")
    _sub(ide, "tpEmis", dados.tp_emis)
    _sub(ide, "cDV", dados.chave.c_dv)
    _sub(ide, "tpAmb", dados.tp_amb)
    _sub(ide, "finNFe", "1")
    _sub(ide, "indFinal", "1")
    _sub(ide, "indPres", "1")
    _sub(ide, "procEmi", "0")
    _sub(ide, "verProc", _limpar(dados.ver_proc, 20))
    if dados.tp_emis == "9":
        _sub(ide, "dhCont", dados.dh_cont)
        _sub(ide, "xJust", _limpar(dados.x_just, 256))

    emitente = dados.emitente
    emit = _sub(inf, "emit")
    _sub(emit, "CNPJ", only_digits(emitente.cnpj).zfill(14))
    _sub(emit, "xNome", _limpar(emitente.razao_social, 60))
    if emitente.nome_fantasia:
        _sub(emit, "xFant", _limpar(emitente.nome_fantasia, 60))
    ender = _sub(emit, "enderEmit")
    _sub(ender, "xLgr", _limpar(emitente.logradouro, 60))
    _sub(ender, "nro", _limpar(emitente.numero, 60) or "S/N")
    if emitente.complemento:
        _sub(ender, "xCpl", _limpar(emitente.complemento, 60))
    _sub(ender, "xBairro", _limpar(emitente.bairro, 60))
    _sub(ender, "cMun", only_digits(emitente.codigo_municipio))
    _sub(ender, "xMun", _limpar(emitente.municipio, 60))
    _sub(ender, "UF", emitente.uf)
    if emitente.cep:
        _sub(ender, "CEP", only_digits(emitente.cep).zfill(8))
    _sub(ender, "cPais", "1058")
    _sub(ender, "xPais", "BRASIL")
    telefone = only_digits(emitente.telefone)
    if 6 <= len(telefone) <= 14:
        _sub(ender, "fone", telefone)
    _sub(emit, "IE", only_digits(emitente.ie))
    _sub(emit, "CRT", emitente.crt)

    cpf = only_digits(dados.cpf_consumidor)
    if cpf:
        dest = _sub(inf, "dest")
        _sub(dest, "CPF", cpf)
        if dados.nome_consumidor or homologacao:
            nome = HOMOLOG_DEST if homologacao else _limpar(dados.nome_consumidor, 60)
            _sub(dest, "xNome", nome)
        _sub(dest, "indIEDest", "9")

    for numero_item, item in enumerate(dados.itens, start=1):
        _append_det(inf, numero_item, item, homologacao and numero_item == 1)

    total = _sub(inf, "total")
    tot = _sub(total, "ICMSTot")
    for tag in ("vBC", "vICMS", "vICMSDeson", "vFCP", "vBCST", "vST", "vFCPST", "vFCPSTRet"):
        _sub(tot, tag, "0.00")
    _sub(tot, "vProd", _fmt2(dados.total_produtos))
    for tag in ("vFrete", "vSeg"):
        _sub(tot, tag, "0.00")
    _sub(tot, "vDesc", _fmt2(dados.total_desconto))
    for tag in ("vII", "vIPI", "vIPIDevol", "vPIS", "vCOFINS", "vOutro"):
        _sub(tot, tag, "0.00")
    _sub(tot, "vNF", _fmt2(dados.total_nota))
    if dados.tributos_aproximados is not None:
        _sub(tot, "vTotTrib", _fmt2(dados.tributos_aproximados))

    transp = _sub(inf, "transp")
    _sub(transp, "modFrete", "9")

    pag = _sub(inf, "pag")
    for pagamento in dados.pagamentos:
        det_pag = _sub(pag, "detPag")
        _sub(det_pag, "tPag", pagamento.t_pag)
        if pagamento.t_pag == "99":
            _sub(det_pag, "xPag", _limpar(pagamento.descricao or "Outros", 60))
        _sub(det_pag, "vPag", _fmt2(pagamento.valor))
        if pagamento.t_pag in TPAG_COM_CARD:
            card = _sub(det_pag, "card")
            _sub(card, "tpIntegra", pagamento.tp_integra or "2")
            cnpj = only_digits(pagamento.cnpj_credenciadora)
            if len(cnpj) == 14:
                _sub(card, "CNPJ", cnpj)
            if pagamento.bandeira and len(only_digits(pagamento.bandeira)) == 2:
                _sub(card, "tBand", only_digits(pagamento.bandeira))
            if pagamento.autorizacao:
                _sub(card, "cAut", _limpar(pagamento.autorizacao, 128))
    if dados.troco > 0:
        _sub(pag, "vTroco", _fmt2(dados.troco))

    inf_cpl_parts = []
    if dados.tributos_aproximados is not None:
        inf_cpl_parts.append(
            f"Trib. aprox. R$ {_fmt2(dados.tributos_aproximados).replace('.', ',')}"
            f" ({Decimal(dados.percentual_tributos):.2f}%) - Lei 12.741/2012."
        )
    if dados.inf_cpl:
        inf_cpl_parts.append(_limpar(dados.inf_cpl, 4000))
    if inf_cpl_parts:
        inf_adic = _sub(inf, "infAdic")
        _sub(inf_adic, "infCpl", _limpar(" ".join(inf_cpl_parts), 5000))

    supl = etree.SubElement(nfe, "infNFeSupl")
    _sub(supl, "qrCode", qrcode)
    _sub(supl, "urlChave", url_chave)
    return etree.tostring(nfe, encoding="unicode")


def _append_det(inf: etree._Element, numero: int, item: ItemNfce, homologacao: bool) -> None:
    det = etree.SubElement(inf, "det", nItem=str(numero))
    prod = _sub(det, "prod")
    gtin = only_digits(item.gtin) if gtin_valido(item.gtin) else SEM_GTIN
    _sub(prod, "cProd", _limpar(item.codigo, 60))
    _sub(prod, "cEAN", gtin)
    _sub(prod, "xProd", HOMOLOG_ITEM if homologacao else _limpar(item.descricao, 120))
    _sub(prod, "NCM", only_digits(item.ncm))
    cest = only_digits(item.cest)
    if len(cest) == 7:
        _sub(prod, "CEST", cest)
    _sub(prod, "CFOP", only_digits(item.cfop) or cfop_padrao(item.csosn))
    unidade = _limpar(item.unidade or "UN", 6) or "UN"
    _sub(prod, "uCom", unidade)
    _sub(prod, "qCom", _fmt_qtd(item.quantidade))
    _sub(prod, "vUnCom", _fmt_unit(item.valor_unitario))
    _sub(prod, "vProd", _fmt2(item.valor_bruto))
    _sub(prod, "cEANTrib", gtin)
    _sub(prod, "uTrib", unidade)
    _sub(prod, "qTrib", _fmt_qtd(item.quantidade))
    _sub(prod, "vUnTrib", _fmt_unit(item.valor_unitario))
    if item.valor_desconto > 0:
        _sub(prod, "vDesc", _fmt2(item.valor_desconto))
    _sub(prod, "indTot", "1")

    imposto = _sub(det, "imposto")
    icms = _sub(imposto, "ICMS")
    if item.csosn in CSOSN_SN500:
        grupo = _sub(icms, "ICMSSN500")
    else:
        grupo = _sub(icms, "ICMSSN102")
    _sub(grupo, "orig", item.origem or "0")
    _sub(grupo, "CSOSN", item.csosn)
    _append_pis_cofins(imposto, "PIS", item.pis_cst)
    _append_pis_cofins(imposto, "COFINS", item.cofins_cst)


def _append_pis_cofins(imposto: etree._Element, tributo: str, cst: str | None) -> None:
    cst = (cst or "99").zfill(2)
    grupo = _sub(imposto, tributo)
    if cst in CST_NT:
        _sub(_sub(grupo, f"{tributo}NT"), "CST", cst)
        return
    if cst not in CST_OUTR:
        cst = "99"
    outr = _sub(grupo, f"{tributo}Outr")
    _sub(outr, "CST", cst)
    _sub(outr, "vBC", "0.00")
    _sub(outr, f"p{tributo}", "0.00")
    _sub(outr, f"v{tributo}", "0.00")
