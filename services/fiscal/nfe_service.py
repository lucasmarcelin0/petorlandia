"""Serviço de emissão NF-e (SEFAZ SP)."""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from flask import current_app
from lxml import etree

# Blindagem XXE: parse de XML externo (resposta SEFAZ) via helper hardened.
from security.xml_safe import safe_lxml_fromstring

from extensions import db
from models import (
    Appointment,
    FiscalCertificate,
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalDocumentType,
    FiscalEmitter,
    FiscalEvent,
    Order,
)
from providers.nfe.chave import montar_chave
from providers.nfe.retorno import parse_autorizacao, parse_consulta_situacao, parse_evento
from providers.nfe.sefaz_sp.client import SefazSpNfeClient, get_sefaz_sp_wsdl_config
from providers.nfe.xml_builder import (
    UF_TO_CUF,
    build_cancel_event_xml,
    build_cons_sit_xml,
    build_envi_nfe_xml,
    build_nfe_proc_xml,
    build_nfe_xml,
    format_dh,
)
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


def create_nfe_document_for_appointment(
    appointment_id: int,
    emitter_id: int,
    payload: dict[str, Any],
) -> FiscalDocument:
    emitter = db.session.get(FiscalEmitter, emitter_id)
    if not emitter:
        raise ValueError("Emissor fiscal não encontrado.")

    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        raise ValueError("Atendimento não encontrado.")

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
        related_type="appointment",
        related_id=appointment.id,
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
    response = client.test_connection(_cuf_for_emitter(emitter))
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

    # Chave e dhEmi ficam gravados: um novo envio (após falha de rede)
    # repete a MESMA chave, e a SEFAZ acusa duplicidade em vez de autorizar
    # duas notas para a mesma venda.
    document.xml_signed = signed_xml
    document.access_key = payload["access_key"]
    document.payload_json = {**(document.payload_json or {}), "dhEmi": payload["ide"]["dhEmi"]}

    client = _build_sefaz_client(certificate, env)
    response = client.autorizacao(build_envi_nfe_xml(signed_xml, id_lote=document.id))

    status, error_code, error_message, authorized_xml, protocol = _handle_autorizacao_response(
        response,
        client,
        tp_amb,
        signed_xml=signed_xml,
        access_key=document.access_key,
    )
    document.status = status
    document.error_code = error_code
    document.error_message = error_message
    if protocol:
        document.protocol = protocol
    if authorized_xml:
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

    # O primeiro cStat do retorno é o do LOTE de eventos (128); o do
    # cancelamento fica em retEvento/infEvento (135 ou 155).
    retorno = parse_evento(response.response or response.response_xml)
    cancel_error = None
    if retorno.registrado:
        document.status = FiscalDocumentStatus.CANCELED
        document.canceled_at = now_in_brazil()
    else:
        # Cancelamento recusado NÃO desfaz a autorização: a nota continua
        # válida e o motivo fica registrado no evento.
        cancel_error = retorno.x_motivo or response.error_message or "Cancelamento não registrado."
        document.error_code = retorno.c_stat
        document.error_message = f"Cancelamento recusado: {cancel_error}"

    _log_event(
        document,
        "cancelamento",
        FiscalDocumentStatus.CANCELED.value if retorno.registrado else "REJECTED",
        request_xml=_redact_xml(response.request_xml),
        response_xml=_redact_xml(response.response_xml),
        protocol=document.protocol,
        error_message=cancel_error,
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
    if not recibo and document.access_key:
        # Envio interrompido antes do retorno: pergunta à SEFAZ pela chave.
        return _sync_by_access_key(document, certificate, env, tp_amb)
    if not recibo:
        raise ValueError("Recibo não disponível para consulta.")

    client = _build_sefaz_client(certificate, env)
    recibo_xml = _build_recibo_xml(recibo, tp_amb)
    response = client.ret_autorizacao(recibo_xml)
    status, error_code, error_message, authorized_xml, protocol = _handle_autorizacao_response(
        response,
        client,
        tp_amb,
        signed_xml=document.xml_signed,
        access_key=document.access_key,
        follow_receipt=False,
    )
    document.status = status
    document.error_code = error_code
    document.error_message = error_message
    if protocol:
        document.protocol = protocol
    if authorized_xml:
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

    # Reenvio da mesma nota: mesma chave e mesmo dhEmi (o AAMM da chave
    # precisa bater com a data de emissão).
    dh_emi = payload.get("dhEmi") if document.access_key and payload.get("dhEmi") else format_dh()
    access_key, c_dv, c_nf = _generate_access_key(emitter, document, dh_emi)
    ide = {
        "cUF": _cuf_for_emitter(emitter),
        "cNF": c_nf,
        "natOp": payload.get("natOp") or "Venda de mercadoria",
        "mod": "55",
        "serie": document.series,
        "nNF": document.number,
        "dhEmi": dh_emi,
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

    if order:
        dest_user = order.user
        endereco_dest = _build_dest_address(order, emitter)
        dest = {
            "CPF": getattr(dest_user, "cpf", None) if dest_user else None,
            "xNome": dest_user.name if dest_user else "Consumidor final",
            "enderDest": endereco_dest,
            "indIEDest": "9",
        }
        items, totals = _build_items(order, emitter)
    else:
        raw_items = payload.get("items") or []
        if not raw_items:
            raise ValueError("Itens da NF-e não informados.")
        dest = dict(payload.get("dest") or {})
        dest.setdefault("xNome", "Consumidor final")
        if "enderDest" not in dest:
            dest["enderDest"] = _default_dest_address(emitter)
        dest.setdefault("indIEDest", "9")
        items, totals = _build_items_from_payload(raw_items, emitter)

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
    v_bc_total = Decimal("0")
    v_icms_total = Decimal("0")
    v_pis_total = Decimal("0")
    v_cofins_total = Decimal("0")

    simples = _crt_from_regime(emitter.regime_tributario) == 1
    for index, item in enumerate(order.items, start=1):
        product = item.product
        quantity = Decimal(str(item.quantity or 1))
        unit_price = Decimal(str(item.unit_price or (product.price if product else 0)))
        v_prod = quantity * unit_price
        # Simples Nacional (CSOSN): sem destaque de ICMS, PIS e COFINS na nota.
        aliquota_icms = Decimal("0") if simples else Decimal(str(getattr(product, "aliquota_icms", 0) or 0))
        aliquota_pis = Decimal("0") if simples else Decimal(str(getattr(product, "aliquota_pis", 0) or 0))
        aliquota_cofins = Decimal("0") if simples else Decimal(str(getattr(product, "aliquota_cofins", 0) or 0))
        v_icms = (v_prod * aliquota_icms) / Decimal("100")
        v_pis = (v_prod * aliquota_pis) / Decimal("100")
        v_cofins = (v_prod * aliquota_cofins) / Decimal("100")

        v_prod_total += v_prod
        if not simples:
            v_bc_total += v_prod
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
        "vBC": _format_decimal(v_bc_total),
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


def _build_items_from_payload(
    raw_items: list[dict[str, Any]],
    emitter: FiscalEmitter,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items: list[dict[str, Any]] = []
    v_prod_total = Decimal("0")
    v_bc_total = Decimal("0")
    v_icms_total = Decimal("0")
    v_pis_total = Decimal("0")
    v_cofins_total = Decimal("0")

    simples = _crt_from_regime(emitter.regime_tributario) == 1
    for index, item in enumerate(raw_items, start=1):
        quantity = Decimal(str(item.get("quantity") or 1))
        unit_price = Decimal(str(item.get("unit_price") or 0))
        v_prod = quantity * unit_price
        # Simples Nacional (CSOSN): sem destaque de ICMS, PIS e COFINS na nota.
        aliquota_icms = Decimal("0") if simples else Decimal(str(item.get("aliquota_icms") or 0))
        aliquota_pis = Decimal("0") if simples else Decimal(str(item.get("aliquota_pis") or 0))
        aliquota_cofins = Decimal("0") if simples else Decimal(str(item.get("aliquota_cofins") or 0))
        v_icms = (v_prod * aliquota_icms) / Decimal("100")
        v_pis = (v_prod * aliquota_pis) / Decimal("100")
        v_cofins = (v_prod * aliquota_cofins) / Decimal("100")

        v_prod_total += v_prod
        if not simples:
            v_bc_total += v_prod
        v_icms_total += v_icms
        v_pis_total += v_pis
        v_cofins_total += v_cofins

        items.append(
            {
                "nItem": index,
                "cProd": str(item.get("code") or item.get("product_id") or index),
                "cEAN": "SEM GTIN",
                "xProd": item.get("name") or "Produto",
                "NCM": item.get("ncm") or "00000000",
                "CFOP": item.get("cfop") or "5102",
                "uCom": item.get("unit") or "UN",
                "qCom": _format_decimal(quantity),
                "vUnCom": _format_decimal(unit_price),
                "vProd": _format_decimal(v_prod),
                "cEANTrib": "SEM GTIN",
                "uTrib": item.get("unit") or "UN",
                "qTrib": _format_decimal(quantity),
                "vUnTrib": _format_decimal(unit_price),
                "indTot": "1",
                "orig": item.get("orig") or "0",
                "cst": None if simples else (item.get("cst") or "00"),
                "csosn": (item.get("csosn") or "102") if simples else None,
                "aliquota_icms": aliquota_icms,
                "vICMS": v_icms,
                "aliquota_pis": aliquota_pis,
                "vPIS": v_pis,
                "aliquota_cofins": aliquota_cofins,
                "vCOFINS": v_cofins,
            }
        )

    totals = {
        "vBC": _format_decimal(v_bc_total),
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


def _default_dest_address(emitter: FiscalEmitter) -> dict[str, Any]:
    return {
        "xLgr": "Endereço não informado",
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


AutorizacaoResultado = tuple[
    FiscalDocumentStatus, Optional[str], Optional[str], Optional[str], Optional[str]
]

# Duplicidade: a chave já foi recebida antes (ex.: retorno perdido na rede).
CSTAT_DUPLICIDADE = {"204"}


def _handle_autorizacao_response(
    response,
    client: SefazSpNfeClient,
    tp_amb: str,
    *,
    signed_xml: str | None = None,
    access_key: str | None = None,
    follow_receipt: bool = True,
) -> AutorizacaoResultado:
    """Traduz o retorno da SEFAZ em (status, código, mensagem, nfeProc, protocolo).

    O protocolo devolvido é o ``nProt`` quando autorizada, ou o ``nRec``
    quando o lote ficou em processamento (usado depois por ``poll_nfe``).
    """
    if not response.success and not response.response:
        # Rede/TLS/timeout: a nota pode ou não ter chegado. FAILED entra no
        # reprocessamento automático, que reenvia a MESMA chave.
        return FiscalDocumentStatus.FAILED, None, response.error_message, None, None

    retorno = parse_autorizacao(response.response or response.response_xml)
    if retorno.autorizado:
        proc = build_nfe_proc_xml(signed_xml, retorno.prot_nfe_xml) if signed_xml else retorno.prot_nfe_xml
        return FiscalDocumentStatus.AUTHORIZED, None, None, proc, retorno.n_prot

    if retorno.em_processamento:
        if not retorno.n_rec:
            return FiscalDocumentStatus.FAILED, retorno.c_stat_lote, retorno.x_motivo_lote, None, None
        if follow_receipt:
            ret_response = client.ret_autorizacao(_build_recibo_xml(retorno.n_rec, tp_amb))
            if ret_response.success or ret_response.response:
                ret = parse_autorizacao(ret_response.response or ret_response.response_xml)
                if ret.autorizado:
                    proc = build_nfe_proc_xml(signed_xml, ret.prot_nfe_xml) if signed_xml else ret.prot_nfe_xml
                    return FiscalDocumentStatus.AUTHORIZED, None, None, proc, ret.n_prot
                if ret.prot_nfe_xml is not None:
                    return FiscalDocumentStatus.REJECTED, ret.c_stat, ret.x_motivo, None, retorno.n_rec
        return FiscalDocumentStatus.PROCESSING, None, None, None, retorno.n_rec

    if retorno.c_stat in CSTAT_DUPLICIDADE and access_key:
        situacao_response = client.consulta_protocolo(build_cons_sit_xml(access_key, tp_amb))
        situacao = parse_consulta_situacao(situacao_response.response or situacao_response.response_xml)
        if situacao.autorizado:
            proc = (
                build_nfe_proc_xml(signed_xml, situacao.prot_nfe_xml)
                if signed_xml and situacao.prot_nfe_xml
                else situacao.prot_nfe_xml
            )
            return FiscalDocumentStatus.AUTHORIZED, None, None, proc, situacao.n_prot

    message = retorno.x_motivo
    if retorno.denegado:
        message = f"Uso denegado: {retorno.x_motivo or retorno.c_stat}"
    return FiscalDocumentStatus.REJECTED, retorno.c_stat, message, None, None


def _sync_by_access_key(
    document: FiscalDocument,
    certificate: FiscalCertificate,
    env: str,
    tp_amb: str,
) -> FiscalDocument:
    """Consulta a chave na SEFAZ quando não há recibo para acompanhar."""
    client = _build_sefaz_client(certificate, env)
    response = client.consulta_protocolo(build_cons_sit_xml(document.access_key, tp_amb))
    situacao = parse_consulta_situacao(response.response or response.response_xml)
    if situacao.autorizado:
        document.status = FiscalDocumentStatus.AUTHORIZED
        document.protocol = situacao.n_prot
        document.error_code = None
        document.error_message = None
        if situacao.prot_nfe_xml:
            document.xml_authorized = (
                build_nfe_proc_xml(document.xml_signed, situacao.prot_nfe_xml)
                if document.xml_signed
                else situacao.prot_nfe_xml
            )
        document.authorized_at = now_in_brazil()
    elif situacao.c_stat == "217":
        # 217: a chave não consta na SEFAZ. Volta para o reprocessamento.
        document.status = FiscalDocumentStatus.FAILED
        document.error_code = situacao.c_stat
        document.error_message = situacao.x_motivo
    _log_event(
        document,
        "consulta_chave",
        document.status.value,
        request_xml=_redact_xml(response.request_xml),
        response_xml=_redact_xml(response.response_xml),
        protocol=document.protocol,
        error_message=None if situacao.autorizado else (situacao.x_motivo or response.error_message),
    )
    db.session.add(document)
    db.session.commit()
    return document


def _build_recibo_xml(recibo: str, tp_amb: str) -> str:
    ns = "http://www.portalfiscal.inf.br/nfe"
    cons = etree.Element("consReciNFe", nsmap={None: ns})
    cons.set("versao", "4.00")
    etree.SubElement(cons, "tpAmb").text = tp_amb
    etree.SubElement(cons, "nRec").text = recibo
    return etree.tostring(cons, encoding="unicode")


def _generate_access_key(
    emitter: FiscalEmitter,
    document: FiscalDocument,
    dh_emi: str | None = None,
) -> tuple[str, str, str]:
    """Chave da nota; reaproveita a já gravada para reenvios da mesma nota.

    O AAMM sai do ``dhEmi`` (antes saía do relógio do servidor em UTC e
    divergia da data de emissão perto da virada do mês) e o ``cNF`` é
    aleatório, diferente do número da nota.
    """
    existing = _only_digits(document.access_key or "")
    if len(existing) == 44:
        return existing, existing[-1], existing[35:43]
    chave = montar_chave(
        c_uf=_cuf_for_emitter(emitter),
        dh_emi=dh_emi or format_dh(),
        cnpj=emitter.cnpj,
        modelo="55",
        serie=document.series or "1",
        numero=document.number or 0,
    )
    return chave.chave, chave.c_dv, chave.c_nf


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
    # Ver comentário em providers/nfe/xml_builder._format_decimal: só os erros
    # realmente esperados de Decimal() caem aqui; TypeError de tipo absurdo
    # (dict, list, etc.) estoura para não esconder bug de chamador.
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
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
        root = safe_lxml_fromstring(xml)
        node = root.find(f".//{tag}")
        if node is None:
            node = root.find(f".//{{*}}{tag}")
        if node is not None and node.text:
            return node.text
    except etree.XMLSyntaxError:
        return None
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(
            "Falha ao extrair tag %s do XML NF-e: %s", tag, exc
        )
        return None
    return None


def _redact_xml(xml: str | None) -> str | None:
    """Delega para security.redact.redact_xml.

    Ganhos vs versão anterior:
      - Cobre Senha/Token/ChaveAcesso, não só CPF/CNPJ/IE.
      - Pega CPF mascarado (123.456.789-00) e CNPJ mascarado
        (12.345.678/0001-90) em texto livre de tags não-sensíveis.
      - Pega chave NF-e (44 dígitos) vazando em logs de erro.
      - Fallback textual quando o XML é malformado.
    """
    from security.redact import redact_xml as _redact

    return _redact(xml)
