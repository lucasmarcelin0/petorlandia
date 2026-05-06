"""XML builders for the Sistema Nacional NFS-e DPS/event layouts."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from zoneinfo import ZoneInfo

from lxml import etree


NFSE_NS = "http://www.sped.fazenda.gov.br/nfse"
BR_TZ = ZoneInfo("America/Sao_Paulo")
DEFAULT_MUNICIPIO_BH = "3106200"


def _digits(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _ns(tag: str) -> str:
    return f"{{{NFSE_NS}}}{tag}"


def _append(parent: etree._Element, tag: str, value: Any | None) -> etree._Element:
    node = etree.SubElement(parent, _ns(tag))
    if value is not None:
        node.text = _text(value)
    return node


def _append_if(parent: etree._Element, tag: str, value: Any | None) -> etree._Element | None:
    if value in (None, "", []):
        return None
    return _append(parent, tag, value)


def _format_decimal(value: Any, default: str = "0.00") -> str:
    if value in (None, ""):
        return default
    try:
        number = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Valor decimal invalido para DPS: {value}") from None
    return f"{number:.2f}"


def _coerce_datetime(value: Any | None) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, time(12, 0))
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.combine(datetime.strptime(raw[:10], "%Y-%m-%d").date(), time(12, 0))
            except ValueError as exc:
                raise ValueError(f"Data/hora de emissao invalida para DPS: {value}") from exc
    else:
        dt = datetime.now(BR_TZ)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BR_TZ)
    return dt.astimezone(BR_TZ).replace(microsecond=0)


def _format_datetime(value: Any | None) -> str:
    return _coerce_datetime(value).isoformat()


def _format_date(value: Any | None) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            try:
                return datetime.strptime(raw[:10], "%Y-%m-%d").date().isoformat()
            except ValueError as exc:
                raise ValueError(f"Data de competencia invalida para DPS: {value}") from exc
    return datetime.now(BR_TZ).date().isoformat()


def _normalize_series(value: Any | None) -> str:
    digits = _digits(value or "1")
    if not digits:
        digits = "1"
    if len(digits) > 5:
        raise ValueError("Serie DPS deve ter ate 5 digitos.")
    return str(int(digits))


def _series_for_id(value: Any | None) -> str:
    return _normalize_series(value).zfill(5)


def _normalize_number(value: Any | None) -> str:
    digits = _digits(value)
    if not digits or int(digits) <= 0:
        raise ValueError("Numero DPS deve ser maior que zero.")
    if len(digits) > 15:
        raise ValueError("Numero DPS deve ter ate 15 digitos.")
    return str(int(digits))


def _normalize_municipio(value: Any | None) -> str:
    digits = _digits(value or DEFAULT_MUNICIPIO_BH)
    if len(digits) != 7:
        raise ValueError("Codigo IBGE do municipio deve ter 7 digitos.")
    return digits


def _tipo_inscricao_federal(doc_digits: str) -> str:
    if len(doc_digits) == 14:
        return "2"
    if len(doc_digits) == 11:
        return "1"
    raise ValueError("CPF/CNPJ do prestador deve ter 11 ou 14 digitos.")


def build_dps_id(codigo_municipio: Any, federal_doc: Any, serie: Any, numero: Any) -> str:
    municipio = _normalize_municipio(codigo_municipio)
    doc_digits = _digits(federal_doc)
    tipo_inscricao = _tipo_inscricao_federal(doc_digits)
    federal_id = doc_digits.zfill(14)
    return f"DPS{municipio}{tipo_inscricao}{federal_id}{_series_for_id(serie)}{_normalize_number(numero).zfill(15)}"


def _normalize_codigo_servico(value: Any | None) -> str:
    digits = _digits(value)
    if len(digits) == 3:
        digits = digits.zfill(4)
    if len(digits) == 4:
        digits = f"{digits}00"
    if len(digits) != 6:
        raise ValueError("Codigo de tributacao nacional deve ter 6 digitos, como 050900.")
    return digits


def _append_document_choice(parent: etree._Element, data: dict[str, Any]) -> None:
    doc = data.get("cpf_cnpj") or data.get("cnpj") or data.get("cpf") or data.get("documento")
    digits = _digits(doc)
    if len(digits) == 14:
        _append(parent, "CNPJ", digits)
    elif len(digits) == 11:
        _append(parent, "CPF", digits)
    else:
        raise ValueError("CPF/CNPJ deve ter 11 ou 14 digitos.")


def _append_address(parent: etree._Element, endereco: dict[str, Any] | None) -> None:
    if not endereco:
        return
    municipio = endereco.get("codigo_municipio") or endereco.get("cMun") or endereco.get("municipio_ibge")
    cep = endereco.get("cep") or endereco.get("CEP")
    logradouro = endereco.get("logradouro") or endereco.get("xLgr")
    numero = endereco.get("numero") or endereco.get("nro") or "S/N"
    bairro = endereco.get("bairro") or endereco.get("xBairro")
    if not (municipio and cep and logradouro and bairro):
        return
    end = etree.SubElement(parent, _ns("end"))
    end_nac = etree.SubElement(end, _ns("endNac"))
    _append(end_nac, "cMun", _normalize_municipio(municipio))
    _append(end_nac, "CEP", _digits(cep))
    _append(end, "xLgr", logradouro)
    _append(end, "nro", numero)
    _append_if(end, "xCpl", endereco.get("complemento") or endereco.get("xCpl"))
    _append(end, "xBairro", bairro)


def _append_person(parent: etree._Element, data: dict[str, Any], *, prestador: bool = False) -> None:
    _append_document_choice(parent, data)
    _append_if(parent, "IM", data.get("im") or data.get("inscricao_municipal"))
    _append_if(parent, "xNome", data.get("nome") or data.get("razao_social") or data.get("nome_fantasia"))
    _append_address(parent, data.get("endereco"))
    _append_if(parent, "fone", _digits(data.get("telefone") or data.get("fone")))
    _append_if(parent, "email", data.get("email"))
    if prestador:
        reg = data.get("regTrib") or {}
        regime = _text(data.get("regime_tributario") or "").lower()
        op_simples = _text(reg.get("opSimpNac") or data.get("opSimpNac"))
        if not op_simples:
            if "mei" in regime:
                op_simples = "2"
            elif "simples" in regime:
                op_simples = "3"
            else:
                op_simples = "1"
        reg_node = etree.SubElement(parent, _ns("regTrib"))
        _append(reg_node, "opSimpNac", op_simples)
        reg_ap = reg.get("regApTribSN") or data.get("regApTribSN")
        if not reg_ap and op_simples == "3":
            reg_ap = "1"
        _append_if(reg_node, "regApTribSN", reg_ap)
        _append(reg_node, "regEspTrib", reg.get("regEspTrib") or data.get("regEspTrib") or "0")


def build_dps_xml(
    payload: dict[str, Any],
    *,
    ambiente: str = "2",
    versao: str = "1.01",
    ver_aplic: str = "Petorlandia-1.0",
) -> str:
    prestador = dict(payload.get("prestador") or {})
    tomador = dict(payload.get("tomador") or {})
    servico = dict(payload.get("servico") or {})
    rps = dict(payload.get("rps") or {})

    municipio = _normalize_municipio(
        payload.get("municipio_ibge")
        or payload.get("codigo_municipio")
        or payload.get("cLocEmi")
        or prestador.get("municipio_ibge")
        or DEFAULT_MUNICIPIO_BH
    )
    serie = _normalize_series(rps.get("serie") or payload.get("serie") or "1")
    numero = _normalize_number(rps.get("numero") or payload.get("numero"))
    prestador_doc = prestador.get("cnpj") or prestador.get("cpf_cnpj") or prestador.get("cpf")
    dps_id = build_dps_id(municipio, prestador_doc, serie, numero)

    root = etree.Element(_ns("DPS"), nsmap={None: NFSE_NS}, versao=versao)
    inf = etree.SubElement(root, _ns("infDPS"), Id=dps_id)
    _append(inf, "tpAmb", ambiente)
    _append(inf, "dhEmi", _format_datetime(rps.get("data_emissao") or payload.get("data_emissao")))
    _append(inf, "verAplic", ver_aplic[:20])
    _append(inf, "serie", serie)
    _append(inf, "nDPS", numero)
    _append(inf, "dCompet", _format_date(payload.get("data_competencia") or payload.get("competencia") or rps.get("data_competencia")))
    _append(inf, "tpEmit", payload.get("tp_emit") or payload.get("tpEmit") or "1")
    _append(inf, "cLocEmi", municipio)

    prest = etree.SubElement(inf, _ns("prest"))
    _append_person(prest, prestador, prestador=True)

    if tomador:
        toma = etree.SubElement(inf, _ns("toma"))
        _append_person(toma, tomador)

    serv = etree.SubElement(inf, _ns("serv"))
    loc_prest = etree.SubElement(serv, _ns("locPrest"))
    _append(loc_prest, "cLocPrestacao", _normalize_municipio(servico.get("codigo_municipio") or payload.get("local_prestacao_ibge") or municipio))
    c_serv = etree.SubElement(serv, _ns("cServ"))
    codigo_servico = (
        servico.get("cTribNac")
        or servico.get("item_lista")
        or payload.get("codigo_servico")
        or payload.get("cTribNac")
    )
    _append(c_serv, "cTribNac", _normalize_codigo_servico(codigo_servico))
    _append_if(c_serv, "cTribMun", servico.get("cTribMun") or servico.get("codigo_tributacao_municipal"))
    _append(c_serv, "xDescServ", servico.get("descricao") or payload.get("descricao") or "Exames de ultrassonografia")
    _append_if(c_serv, "cNBS", _digits(servico.get("cNBS") or servico.get("codigo_nbs")))
    _append_if(c_serv, "cIntContrib", servico.get("cIntContrib") or servico.get("codigo_interno"))

    valores = etree.SubElement(inf, _ns("valores"))
    v_serv_prest = etree.SubElement(valores, _ns("vServPrest"))
    _append(v_serv_prest, "vServ", _format_decimal(servico.get("valor") or payload.get("valor_total")))
    trib = etree.SubElement(valores, _ns("trib"))
    trib_mun = etree.SubElement(trib, _ns("tribMun"))
    _append(trib_mun, "tribISSQN", payload.get("tribISSQN") or servico.get("tribISSQN") or "1")
    _append(trib_mun, "tpRetISSQN", "2" if payload.get("iss_retido") else (payload.get("tpRetISSQN") or servico.get("tpRetISSQN") or "1"))
    aliquota = servico.get("aliquota_iss") or payload.get("aliquota_iss")
    _append_if(trib_mun, "pAliq", _format_decimal(aliquota) if aliquota not in (None, "") else None)
    tot_trib = etree.SubElement(trib, _ns("totTrib"))
    _append(tot_trib, "indTotTrib", "0")

    return etree.tostring(root, encoding="unicode")


def build_cancel_event_xml(
    access_key: str,
    author_doc: Any,
    *,
    reason_code: str = "1",
    reason_description: str = "Erro na emissao",
    ambiente: str = "2",
    versao: str = "1.01",
    ver_aplic: str = "Petorlandia-1.0",
    sequence: int = 1,
    event_datetime: Any | None = None,
) -> str:
    chave = _digits(access_key)
    if len(chave) != 50:
        raise ValueError("Chave de acesso da NFS-e deve ter 50 digitos.")
    event_code = "101101"
    seq = str(sequence).zfill(3)
    root = etree.Element(_ns("pedRegEvento"), nsmap={None: NFSE_NS}, versao=versao)
    inf = etree.SubElement(root, _ns("infPedReg"), Id=f"PRE{chave}{event_code}{seq}")
    _append(inf, "tpAmb", ambiente)
    _append(inf, "verAplic", ver_aplic[:20])
    _append(inf, "dhEvento", _format_datetime(event_datetime))
    author_digits = _digits(author_doc)
    if len(author_digits) == 14:
        _append(inf, "CNPJAutor", author_digits)
    elif len(author_digits) == 11:
        _append(inf, "CPFAutor", author_digits)
    else:
        raise ValueError("CPF/CNPJ do autor do evento deve ter 11 ou 14 digitos.")
    _append(inf, "chNFSe", chave)
    event = etree.SubElement(inf, _ns("e101101"))
    _append(event, "xDesc", "Cancelamento de NFS-e")
    _append(event, "cMotivo", reason_code if reason_code in {"1", "2", "9"} else "9")
    _append(event, "xMotivo", reason_description or "Cancelamento solicitado pelo emissor")
    return etree.tostring(root, encoding="unicode")
