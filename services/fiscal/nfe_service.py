"""Serviço de emissão NF-e (SEFAZ SP)."""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from flask import current_app
from lxml import etree

from extensions import db
from models import (
    FiscalCertificate,
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalDocumentType,
    FiscalEmitter,
    FiscalEvent,
    Order,
)
from providers.nfe.sefaz_sp.client import SefazSpNfeClient, get_sefaz_sp_wsdl_config
from providers.nfe.xml_builder import UF_TO_CUF, build_cancel_event_xml, build_nfe_xml
from providers.nfe.xml_signer import sign_event_xml, sign_nfe_xml
from security.crypto import decrypt_bytes, decrypt_text
from services.fiscal.numbering import reserve_next_number
from time_utils import now_in_brazil


def create_nfe_document(
    order_id: int,
    emitter_id: int,
    payload: Optional[dict[str, Any]] = None,
) -> FiscalDocument:
    emitter = db.session.get(FiscalEmitter, emitter_id)
    if not emitter:
        raise ValueError("Emissor fiscal não encontrado.")

    order = db.session.get(Order, order_id)
    if not order:
        raise ValueError("Pedido não encontrado.")

    payload = payload or _build_payload_from_order(order)
    series = str(payload.get("serie") or "1")
    number = reserve_next_number(emitter.id, FiscalDocumentType.NFE, series)

    document = FiscalDocument(
        emitter_id=emitter.id,
        clinic_id=emitter.clinic_id,
        doc_type=FiscalDocumentType.NFE,
        status=FiscalDocumentStatus.QUEUED,
        series=series,
        number=number,
        payload_json=payload,
        related_type="order",
        related_id=order.id,
    )
    db.session.add(document)
    db.session.flush()
    _log_event(document, "queued", FiscalDocumentStatus.QUEUED.value)
    db.session.commit()
    return document


def queue_emit_nfe(document_id: int) -> None:
    try:
        from app.jobs.fiscal_tasks import emit_nfe

        emit_nfe.delay(document_id)
    except Exception:  # noqa: BLE001 - fallback para ambientes sem celery
        current_app.logger.warning("Fila Celery indisponível, processando emissão local.")
        emit_nfe_sync(document_id)


def test_nfe_connection(emitter_id: int) -> dict[str, Any]:
    emitter = db.session.get(FiscalEmitter, emitter_id)
    if not emitter:
        raise ValueError("Emissor fiscal não encontrado.")
    certificate = _get_active_certificate(emitter.id)
    if not certificate:
        raise ValueError("Certificado fiscal A1 não encontrado.")
    env = os.getenv("NFE_ENV", "homolog")
    client = _build_sefaz_client(certificate, env)
    response = client.test_connection()
    return {
        "success": response.success,
        "error_message": response.error_message,
        "env": env,
        "wsdl": client.wsdl_config.autorizacao,
    }


def emit_nfe_sync(document_id: int) -> FiscalDocument:
    document = db.session.get(FiscalDocument, document_id)
    if not document:
        raise ValueError("Documento fiscal não encontrado.")
    if document.status == FiscalDocumentStatus.AUTHORIZED:
        return document

    document.status = FiscalDocumentStatus.PROCESSING
    db.session.add(document)
    db.session.commit()
    _log_event(document, "sending", FiscalDocumentStatus.PROCESSING.value)

    emitter = document.emitter
    if not emitter:
        raise ValueError("Emissor fiscal não configurado.")

    certificate = _get_active_certificate(emitter.id)
    if not certificate:
        raise ValueError("Certificado fiscal A1 não encontrado.")

    env = os.getenv("NFE_ENV", "homolog")
    tp_amb = "2" if env == "homolog" else "1"
    payload = _normalize_payload(document, emitter, tp_amb)
    xml = build_nfe_xml(payload)
    signed_xml = sign_nfe_xml(
        xml,
        pfx_bytes=decrypt_bytes(certificate.pfx_encrypted),
        password=decrypt_text(certificate.pfx_password_encrypted),
    )

    client = _build_sefaz_client(certificate, env)
    response = client.autorizacao(signed_xml)

    document.xml_signed = signed_xml
    document.access_key = payload["access_key"]
    protocol = _extract_xml_value(response.response_xml or "", "nProt")
    if protocol:
        document.protocol = protocol
    else:
        document.protocol = _extract_xml_value(response.response_xml or "", "nRec")

    status, error_code, error_message, authorized_xml = _handle_autorizacao_response(
        response,
        client,
        tp_amb,
    )
    document.status = status
    document.error_code = error_code
    document.error_message = error_message
    document.xml_authorized = authorized_xml
    if status == FiscalDocumentStatus.AUTHORIZED:
        document.authorized_at = now_in_brazil()

    _log_event(
        document,
        "autorizacao",
        document.status.value,
        request_xml=_redact_xml(response.request_xml),
        response_xml=_redact_xml(response.response_xml),
        protocol=document.protocol,
        error_message=document.error_message,
    )

    db.session.add(document)
    db.session.commit()
    return document


def cancel_nfe_document(document_id: int, reason: Optional[str] = None) -> FiscalDocument:
    document = db.session.get(FiscalDocument, document_id)
    if not document:
        raise ValueError("Documento fiscal não encontrado.")
    if document.status == FiscalDocumentStatus.CANCELED:
        return document

    emitter = document.emitter
    certificate = _get_active_certificate(emitter.id) if emitter else None
    if not emitter or not certificate:
        raise ValueError("Configuração fiscal incompleta.")
    if not document.access_key or not document.protocol:
        raise ValueError("Documento não possui chave ou protocolo para cancelamento.")

    env = os.getenv("NFE_ENV", "homolog")
    tp_amb = "2" if env == "homolog" else "1"
    motivo = (reason or "Cancelamento solicitado").strip()
    if len(motivo) < 15:
        motivo = f"{motivo} - cancelamento"

    xml_evento = build_cancel_event_xml(
        chave=document.access_key,
        emitter_cnpj=emitter.cnpj,
        protocolo=document.protocol,
        motivo=motivo,
        tp_amb=tp_amb,
    )
    signed_event = sign_event_xml(
        xml_evento,
        pfx_bytes=decrypt_bytes(certificate.pfx_encrypted),
        password=decrypt_text(certificate.pfx_password_encrypted),
    )
    client = _build_sefaz_client(certificate, env)
    response = client.evento_cancelamento(document.access_key, signed_event)

    status_code = _extract_xml_value(response.response_xml or "", "cStat")
    if status_code == "135":
        document.status = FiscalDocumentStatus.CANCELED
        document.canceled_at = now_in_brazil()
    else:
        document.status = FiscalDocumentStatus.REJECTED
        document.error_code = status_code
        document.error_message = _extract_xml_value(response.response_xml or "", "xMotivo")

    _log_event(
        document,
        "cancelamento",
        document.status.value,
        request_xml=_redact_xml(response.request_xml),
        response_xml=_redact_xml(response.response_xml),
        protocol=document.protocol,
        error_message=document.error_message,
    )
    db.session.add(document)
    db.session.commit()
    return document


def poll_nfe(document_id: int) -> FiscalDocument:
    document = db.session.get(FiscalDocument, document_id)
    if not document:
        raise ValueError("Documento fiscal não encontrado.")
    if document.status in {FiscalDocumentStatus.AUTHORIZED, FiscalDocumentStatus.REJECTED}:
        return document

    emitter = document.emitter
    certificate = _get_active_certificate(emitter.id) if emitter else None
    if not emitter or not certificate:
        raise ValueError("Configuração fiscal incompleta.")

    env = os.getenv("NFE_ENV", "homolog")
    tp_amb = "2" if env == "homolog" else "1"
    recibo = document.protocol
    if not recibo:
        raise ValueError("Recibo não disponível para consulta.")

    client = _build_sefaz_client(certificate, env)
    recibo_xml = _build_recibo_xml(recibo, tp_amb)
    response = client.ret_autorizacao(recibo_xml)
    status, error_code, error_message, authorized_xml = _handle_autorizacao_response(
        response,
        client,
        tp_amb,
    )
    document.status = status
    document.error_code = error_code
    document.error_message = error_message
    document.xml_authorized = authorized_xml
    if status == FiscalDocumentStatus.AUTHORIZED:
        document.authorized_at = now_in_brazil()

    _log_event(
        document,
        "consulta",
        document.status.value,
        request_xml=_redact_xml(response.request_xml),
        response_xml=_redact_xml(response.response_xml),
        protocol=document.protocol,
        error_message=document.error_message,
    )
    db.session.add(document)
    db.session.commit()
    return document


def _build_payload_from_order(order: Order) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "items": [
            {
                "product_id": item.product_id,
                "name": item.item_name,
                "quantity": int(item.quantity or 1),
                "unit_price": float(item.unit_price or (item.product.price if item.product else 0)),
            }
            for item in order.items
        ],
    }


def _normalize_payload(
    document: FiscalDocument,
    emitter: FiscalEmitter,
    tp_amb: str,
) -> dict[str, Any]:
    payload = dict(document.payload_json or {})
    order = db.session.get(Order, document.related_id) if document.related_type == "order" else None
    if not order:
        raise ValueError("Pedido relacionado não encontrado.")

    access_key, c_dv, c_nf = _generate_access_key(emitter, document)
    ide = {
        "cUF": _cuf_for_emitter(emitter),
        "cNF": c_nf,
        "natOp": payload.get("natOp") or "Venda de mercadoria",
        "mod": "55",
        "serie": document.series,
        "nNF": document.number,
        "dhEmi": now_in_brazil().isoformat(),
        "tpNF": "1",
        "idDest": "1",
        "cMunFG": emitter.municipio_ibge or "",
        "tpImp": "1",
        "tpEmis": "1",
        "cDV": c_dv,
        "tpAmb": tp_amb,
        "finNFe": "1",
        "indFinal": "1",
        "indPres": "1",
        "procEmi": "0",
        "verProc": "petorlandia",
    }

    endereco_emit = emitter.endereco_json or {}
    emit = {
        "CNPJ": emitter.cnpj,
        "xNome": emitter.razao_social,
        "xFant": emitter.nome_fantasia,
        "IE": emitter.inscricao_estadual or "",
        "enderEmit": {
            "xLgr": endereco_emit.get("logradouro") or endereco_emit.get("rua"),
            "nro": endereco_emit.get("numero"),
            "xBairro": endereco_emit.get("bairro"),
            "cMun": endereco_emit.get("codigo_municipio") or emitter.municipio_ibge,
            "xMun": endereco_emit.get("cidade"),
            "UF": emitter.uf,
            "CEP": endereco_emit.get("cep"),
            "cPais": "1058",
            "xPais": "BRASIL",
            "fone": endereco_emit.get("telefone"),
        },
        "CRT": _crt_from_regime(emitter.regime_tributario),
    }

    dest_user = order.user
    endereco_dest = _build_dest_address(order, emitter)
    dest = {
        "CPF": getattr(dest_user, "cpf", None) if dest_user else None,
        "xNome": dest_user.name if dest_user else "Consumidor final",
        "enderDest": endereco_dest,
        "indIEDest": "9",
    }

    items, totals = _build_items(order, emitter)
    return {
        "access_key": access_key,
        "ide": ide,
        "emit": emit,
        "dest": dest,
        "items": items,
        "totals": totals,
        "inf_adic": payload.get("inf_adic"),
    }


def _build_items(order: Order, emitter: FiscalEmitter) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items: list[dict[str, Any]] = []
    v_prod_total = Decimal("0")
    v_icms_total = Decimal("0")
    v_pis_total = Decimal("0")
    v_cofins_total = Decimal("0")

    simples = _crt_from_regime(emitter.regime_tributario) == 1
    for index, item in enumerate(order.items, start=1):
        product = item.product
        quantity = Decimal(str(item.quantity or 1))
        unit_price = Decimal(str(item.unit_price or (product.price if product else 0)))
        v_prod = quantity * unit_price
        aliquota_icms = Decimal(str(getattr(product, "aliquota_icms", 0) or 0))
        aliquota_pis = Decimal(str(getattr(product, "aliquota_pis", 0) or 0))
        aliquota_cofins = Decimal(str(getattr(product, "aliquota_cofins", 0) or 0))
        v_icms = (v_prod * aliquota_icms) / Decimal("100")
        v_pis = (v_prod * aliquota_pis) / Decimal("100")
        v_cofins = (v_prod * aliquota_cofins) / Decimal("100")

        v_prod_total += v_prod
        v_icms_total += v_icms
        v_pis_total += v_pis
        v_cofins_total += v_cofins

        items.append(
            {
                "nItem": index,
                "cProd": str(product.id if product else item.product_id),
                "cEAN": "SEM GTIN",
                "xProd": item.item_name,
                "NCM": product.ncm if product and product.ncm else "00000000",
                "CFOP": product.cfop if product and product.cfop else "5102",
                "uCom": product.unidade if product and product.unidade else "UN",
                "qCom": _format_decimal(quantity),
                "vUnCom": _format_decimal(unit_price),
                "vProd": _format_decimal(v_prod),
                "cEANTrib": "SEM GTIN",
                "uTrib": product.unidade if product and product.unidade else "UN",
                "qTrib": _format_decimal(quantity),
                "vUnTrib": _format_decimal(unit_price),
                "indTot": "1",
                "orig": product.origem if product and product.origem else "0",
                "cst": None if simples else (product.cst if product and product.cst else "00"),
                "csosn": (product.csosn if product and product.csosn else "102") if simples else None,
                "aliquota_icms": aliquota_icms,
                "vICMS": v_icms,
                "aliquota_pis": aliquota_pis,
                "vPIS": v_pis,
                "aliquota_cofins": aliquota_cofins,
                "vCOFINS": v_cofins,
            }
        )

    totals = {
        "vBC": _format_decimal(v_prod_total),
        "vICMS": _format_decimal(v_icms_total),
        "vICMSDeson": "0.00",
        "vFCP": "0.00",
        "vBCST": "0.00",
        "vST": "0.00",
        "vFCPST": "0.00",
        "vFCPSTRet": "0.00",
        "vProd": _format_decimal(v_prod_total),
        "vFrete": "0.00",
        "vSeg": "0.00",
        "vDesc": "0.00",
        "vII": "0.00",
        "vIPI": "0.00",
        "vIPIDevol": "0.00",
        "vPIS": _format_decimal(v_pis_total),
        "vCOFINS": _format_decimal(v_cofins_total),
        "vOutro": "0.00",
        "vNF": _format_decimal(v_prod_total),
    }
    return items, totals


def _build_dest_address(order: Order, emitter: FiscalEmitter) -> dict[str, Any]:
    endereco_texto = (order.shipping_address or "").strip()
    return {
        "xLgr": endereco_texto or "Endereço não informado",
        "nro": "S/N",
        "xBairro": "Centro",
        "cMun": emitter.municipio_ibge or "",
        "xMun": (emitter.endereco_json or {}).get("cidade"),
        "UF": emitter.uf,
        "CEP": (emitter.endereco_json or {}).get("cep"),
        "cPais": "1058",
        "xPais": "BRASIL",
    }


def _get_active_certificate(emitter_id: int) -> FiscalCertificate | None:
    return (
        FiscalCertificate.query
        .filter_by(emitter_id=emitter_id)
        .order_by(FiscalCertificate.created_at.desc())
        .first()
    )


def _build_sefaz_client(certificate: FiscalCertificate, env: str) -> SefazSpNfeClient:
    wsdl_config = get_sefaz_sp_wsdl_config(env)
    return SefazSpNfeClient(
        wsdl_config=wsdl_config,
        pfx_bytes=decrypt_bytes(certificate.pfx_encrypted),
        pfx_password=decrypt_text(certificate.pfx_password_encrypted),
    )


def _handle_autorizacao_response(
    response,
    client: SefazSpNfeClient,
    tp_amb: str,
) -> tuple[FiscalDocumentStatus, str | None, str | None, str | None]:
    c_stat = _extract_xml_value(response.response_xml or "", "cStat")
    x_motivo = _extract_xml_value(response.response_xml or "", "xMotivo")
    if c_stat in {"100", "150"}:
        return FiscalDocumentStatus.AUTHORIZED, None, None, response.response_xml
    if c_stat == "103":
        recibo = _extract_xml_value(response.response_xml or "", "nRec")
        if not recibo:
            return FiscalDocumentStatus.REJECTED, c_stat, x_motivo, response.response_xml
        recibo_xml = _build_recibo_xml(recibo, tp_amb)
        ret_response = client.ret_autorizacao(recibo_xml)
        ret_cstat = _extract_xml_value(ret_response.response_xml or "", "cStat")
        ret_motivo = _extract_xml_value(ret_response.response_xml or "", "xMotivo")
        if ret_cstat in {"100", "150"}:
            return FiscalDocumentStatus.AUTHORIZED, None, None, ret_response.response_xml
        return FiscalDocumentStatus.REJECTED, ret_cstat, ret_motivo, ret_response.response_xml
    return FiscalDocumentStatus.REJECTED, c_stat, x_motivo, response.response_xml


def _build_recibo_xml(recibo: str, tp_amb: str) -> str:
    ns = "http://www.portalfiscal.inf.br/nfe"
    cons = etree.Element("consReciNFe", nsmap={None: ns})
    cons.set("versao", "4.00")
    etree.SubElement(cons, "tpAmb").text = tp_amb
    etree.SubElement(cons, "nRec").text = recibo
    return etree.tostring(cons, encoding="unicode")


def _generate_access_key(emitter: FiscalEmitter, document: FiscalDocument) -> tuple[str, str, str]:
    c_uf = _cuf_for_emitter(emitter)
    data = datetime.now().strftime("%y%m")
    cnpj = _only_digits(emitter.cnpj).zfill(14)
    modelo = "55"
    serie = str(document.series).zfill(3)
    numero = str(document.number).zfill(9)
    tp_emis = "1"
    c_nf = str(int(datetime.utcnow().timestamp()))[-8:]
    base = f"{c_uf}{data}{cnpj}{modelo}{serie}{numero}{tp_emis}{c_nf}"
    dv = _mod11(base)
    return f"{base}{dv}", str(dv), c_nf


def _cuf_for_emitter(emitter: FiscalEmitter) -> str:
    if emitter.uf and emitter.uf in UF_TO_CUF:
        return UF_TO_CUF[emitter.uf]
    return "35"


def _mod11(value: str) -> int:
    weights = list(range(2, 10))
    total = 0
    weight_index = 0
    for digit in reversed(value):
        total += int(digit) * weights[weight_index]
        weight_index = (weight_index + 1) % len(weights)
    remainder = total % 11
    return 0 if remainder in (0, 1) else 11 - remainder


def _crt_from_regime(regime: str | None) -> int:
    if regime and "simples" in regime.lower():
        return 1
    return 3


def _format_decimal(value: Decimal | str | float | int) -> str:
    try:
        decimal_value = Decimal(str(value))
    except Exception:  # noqa: BLE001
        decimal_value = Decimal("0")
    return f"{decimal_value:.2f}"


def _only_digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _log_event(
    document: FiscalDocument,
    event_type: str,
    status: str,
    request_xml: str | None = None,
    response_xml: str | None = None,
    protocol: str | None = None,
    error_message: str | None = None,
) -> None:
    event = FiscalEvent(
        document_id=document.id,
        event_type=event_type,
        status=status,
        request_xml=request_xml,
        response_xml=response_xml,
        protocol=protocol,
        error_message=error_message,
    )
    db.session.add(event)


def _extract_xml_value(xml: str, tag: str) -> str | None:
    if not xml:
        return None
    try:
        root = etree.fromstring(xml.encode("utf-8"))
        node = root.find(f".//{tag}")
        if node is None:
            node = root.find(f".//{{*}}{tag}")
        if node is not None and node.text:
            return node.text
    except Exception:  # noqa: BLE001
        return None
    return None


def _redact_xml(xml: str | None) -> str | None:
    if not xml:
        return xml
    try:
        root = etree.fromstring(xml.encode("utf-8"))
        for tag in ["CPF", "CNPJ", "IE"]:
            for node in root.findall(f".//{tag}"):
                if node.text:
                    node.text = "***"
        return etree.tostring(root, encoding="unicode")
    except Exception:  # noqa: BLE001
        return xml
