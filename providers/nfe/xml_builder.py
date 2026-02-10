"""Builder XML NF-e (modelo 55, versão 4.00)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from lxml import etree


UF_TO_CUF = {
    "RO": "11",
    "AC": "12",
    "AM": "13",
    "RR": "14",
    "PA": "15",
    "AP": "16",
    "TO": "17",
    "MA": "21",
    "PI": "22",
    "CE": "23",
    "RN": "24",
    "PB": "25",
    "PE": "26",
    "AL": "27",
    "SE": "28",
    "BA": "29",
    "MG": "31",
    "ES": "32",
    "RJ": "33",
    "SP": "35",
    "PR": "41",
    "SC": "42",
    "RS": "43",
    "MS": "50",
    "MT": "51",
    "GO": "52",
    "DF": "53",
}


def build_nfe_xml(payload: dict[str, Any]) -> str:
    """Gera XML NF-e simplificado a partir de payload normalizado."""
    ns = "http://www.portalfiscal.inf.br/nfe"
    nfe = etree.Element("NFe", nsmap={None: ns})
    inf_nfe = etree.SubElement(
        nfe,
        "infNFe",
        Id=f"NFe{payload['access_key']}",
        versao="4.00",
    )

    _append_ide(inf_nfe, payload["ide"])
    _append_emit(inf_nfe, payload["emit"])
    _append_dest(inf_nfe, payload["dest"])
    for item in payload["items"]:
        _append_det(inf_nfe, item)
    _append_total(inf_nfe, payload["totals"])
    _append_transp(inf_nfe)
    _append_pag(inf_nfe, payload["totals"]["vNF"])
    _append_inf_adic(inf_nfe, payload.get("inf_adic"))
    return etree.tostring(nfe, encoding="unicode")


def build_cancel_event_xml(
    chave: str,
    emitter_cnpj: str,
    protocolo: str,
    motivo: str,
    sequencia: int = 1,
    tp_amb: str = "2",
    data_evento: datetime | None = None,
) -> str:
    ns = "http://www.portalfiscal.inf.br/nfe"
    env_evento = etree.Element("envEvento", nsmap={None: ns})
    env_evento.set("versao", "1.00")
    etree.SubElement(env_evento, "idLote").text = "1"
    evento = etree.SubElement(env_evento, "evento", versao="1.00")
    seq = f"{sequencia:02d}"
    inf_evento = etree.SubElement(
        evento,
        "infEvento",
        Id=f"ID110111{chave}{seq}",
    )
    dh_evento = (data_evento or datetime.utcnow()).isoformat()
    etree.SubElement(inf_evento, "cOrgao").text = chave[:2]
    etree.SubElement(inf_evento, "tpAmb").text = tp_amb
    etree.SubElement(inf_evento, "CNPJ").text = _only_digits(emitter_cnpj)
    etree.SubElement(inf_evento, "chNFe").text = chave
    etree.SubElement(inf_evento, "dhEvento").text = dh_evento
    etree.SubElement(inf_evento, "tpEvento").text = "110111"
    etree.SubElement(inf_evento, "nSeqEvento").text = str(sequencia)
    etree.SubElement(inf_evento, "verEvento").text = "1.00"
    det_evento = etree.SubElement(inf_evento, "detEvento", versao="1.00")
    etree.SubElement(det_evento, "descEvento").text = "Cancelamento"
    etree.SubElement(det_evento, "nProt").text = protocolo
    etree.SubElement(det_evento, "xJust").text = motivo
    return etree.tostring(env_evento, encoding="unicode")


def _append_ide(parent: etree._Element, ide_data: dict[str, Any]) -> None:
    ide = etree.SubElement(parent, "ide")
    for key, value in ide_data.items():
        if value is None:
            continue
        etree.SubElement(ide, key).text = str(value)


def _append_emit(parent: etree._Element, emit_data: dict[str, Any]) -> None:
    emit = etree.SubElement(parent, "emit")
    etree.SubElement(emit, "CNPJ").text = _only_digits(emit_data["CNPJ"])
    etree.SubElement(emit, "xNome").text = emit_data["xNome"]
    if emit_data.get("xFant"):
        etree.SubElement(emit, "xFant").text = emit_data["xFant"]
    ender = etree.SubElement(emit, "enderEmit")
    for key, value in emit_data.get("enderEmit", {}).items():
        if value is None:
            continue
        etree.SubElement(ender, key).text = str(value)
    if emit_data.get("IE"):
        etree.SubElement(emit, "IE").text = emit_data["IE"]
    if emit_data.get("CRT"):
        etree.SubElement(emit, "CRT").text = str(emit_data["CRT"])


def _append_dest(parent: etree._Element, dest_data: dict[str, Any]) -> None:
    dest = etree.SubElement(parent, "dest")
    if dest_data.get("CPF"):
        etree.SubElement(dest, "CPF").text = _only_digits(dest_data["CPF"])
    if dest_data.get("CNPJ"):
        etree.SubElement(dest, "CNPJ").text = _only_digits(dest_data["CNPJ"])
    etree.SubElement(dest, "xNome").text = dest_data["xNome"]
    if dest_data.get("enderDest"):
        ender = etree.SubElement(dest, "enderDest")
        for key, value in dest_data["enderDest"].items():
            if value is None:
                continue
            etree.SubElement(ender, key).text = str(value)
    if dest_data.get("indIEDest") is not None:
        etree.SubElement(dest, "indIEDest").text = str(dest_data["indIEDest"])


def _append_det(parent: etree._Element, item: dict[str, Any]) -> None:
    det = etree.SubElement(parent, "det", nItem=str(item["nItem"]))
    prod = etree.SubElement(det, "prod")
    for key in [
        "cProd",
        "cEAN",
        "xProd",
        "NCM",
        "CFOP",
        "uCom",
        "qCom",
        "vUnCom",
        "vProd",
        "cEANTrib",
        "uTrib",
        "qTrib",
        "vUnTrib",
        "indTot",
    ]:
        if key not in item:
            continue
        etree.SubElement(prod, key).text = str(item[key])

    imposto = etree.SubElement(det, "imposto")
    icms = etree.SubElement(imposto, "ICMS")
    if item.get("csosn"):
        icms_tag = etree.SubElement(icms, "ICMSSN102")
        etree.SubElement(icms_tag, "orig").text = str(item.get("orig") or "0")
        etree.SubElement(icms_tag, "CSOSN").text = str(item["csosn"])
    else:
        icms_tag = etree.SubElement(icms, "ICMS00")
        etree.SubElement(icms_tag, "orig").text = str(item.get("orig") or "0")
        etree.SubElement(icms_tag, "CST").text = str(item.get("cst") or "00")
        etree.SubElement(icms_tag, "modBC").text = "3"
        etree.SubElement(icms_tag, "vBC").text = str(item["vProd"])
        etree.SubElement(icms_tag, "pICMS").text = _format_decimal(item.get("aliquota_icms") or Decimal("0"))
        etree.SubElement(icms_tag, "vICMS").text = _format_decimal(item.get("vICMS") or Decimal("0"))

    pis = etree.SubElement(imposto, "PIS")
    pis_tag = etree.SubElement(pis, "PISAliq")
    etree.SubElement(pis_tag, "CST").text = str(item.get("pis_cst") or "01")
    etree.SubElement(pis_tag, "vBC").text = str(item["vProd"])
    etree.SubElement(pis_tag, "pPIS").text = _format_decimal(item.get("aliquota_pis") or Decimal("0"))
    etree.SubElement(pis_tag, "vPIS").text = _format_decimal(item.get("vPIS") or Decimal("0"))

    cofins = etree.SubElement(imposto, "COFINS")
    cofins_tag = etree.SubElement(cofins, "COFINSAliq")
    etree.SubElement(cofins_tag, "CST").text = str(item.get("cofins_cst") or "01")
    etree.SubElement(cofins_tag, "vBC").text = str(item["vProd"])
    etree.SubElement(cofins_tag, "pCOFINS").text = _format_decimal(item.get("aliquota_cofins") or Decimal("0"))
    etree.SubElement(cofins_tag, "vCOFINS").text = _format_decimal(item.get("vCOFINS") or Decimal("0"))


def _append_total(parent: etree._Element, totals: dict[str, Any]) -> None:
    total = etree.SubElement(parent, "total")
    icms_tot = etree.SubElement(total, "ICMSTot")
    for key, value in totals.items():
        etree.SubElement(icms_tot, key).text = str(value)


def _append_transp(parent: etree._Element) -> None:
    transp = etree.SubElement(parent, "transp")
    etree.SubElement(transp, "modFrete").text = "9"


def _append_pag(parent: etree._Element, total: Decimal) -> None:
    pag = etree.SubElement(parent, "pag")
    det_pag = etree.SubElement(pag, "detPag")
    etree.SubElement(det_pag, "indPag").text = "0"
    etree.SubElement(det_pag, "tPag").text = "01"
    etree.SubElement(det_pag, "vPag").text = _format_decimal(total)


def _append_inf_adic(parent: etree._Element, info: str | None) -> None:
    if not info:
        return
    inf_adic = etree.SubElement(parent, "infAdic")
    etree.SubElement(inf_adic, "infCpl").text = info


def _format_decimal(value: Decimal | str | float | int) -> str:
    try:
        decimal_value = Decimal(str(value))
    except Exception:  # noqa: BLE001
        decimal_value = Decimal("0")
    return f"{decimal_value:.2f}"


def _only_digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())
