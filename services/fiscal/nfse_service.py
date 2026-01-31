"""Serviço de emissão NFS-e (Betha/Orlândia)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from flask import current_app

from lxml import etree

from extensions import db
from models import (
    Appointment,
    FiscalCertificate,
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalDocumentType,
    FiscalEmitter,
    FiscalEvent,
    Orcamento,
)
from providers.nfse.betha import build_lote_xml, sign_betha_xml
from providers.nfse.betha.client import BethaNfseClient
from providers.nfse.betha.client import BethaWsdlConfig
from security.crypto import decrypt_bytes, decrypt_text
from services.fiscal.numbering import reserve_next_number
from time_utils import now_in_brazil


def create_nfse_document(
    related_type: str,
    related_id: int,
    emitter_id: int,
    payload: dict[str, Any],
) -> FiscalDocument:
    emitter = db.session.get(FiscalEmitter, emitter_id)
    if not emitter:
        raise ValueError("Emissor fiscal não encontrado.")

    series = str(payload.get("serie") or "1")
    number = reserve_next_number(emitter.id, FiscalDocumentType.NFSE, series)

    document = FiscalDocument(
        emitter_id=emitter.id,
        clinic_id=emitter.clinic_id,
        doc_type=FiscalDocumentType.NFSE,
        status=FiscalDocumentStatus.QUEUED,
        series=series,
        number=number,
        payload_json=payload,
        related_type=related_type,
        related_id=related_id,
    )
    db.session.add(document)
    db.session.flush()
    _log_event(document, "queued", FiscalDocumentStatus.QUEUED.value)
    db.session.commit()
    return document


def create_nfse_draft_from_orcamento(orcamento_id: int) -> FiscalDocument:
    orcamento = db.session.get(Orcamento, orcamento_id)
    if not orcamento:
        raise ValueError("Orçamento não encontrado.")

    emitter = FiscalEmitter.query.filter_by(clinic_id=orcamento.clinica_id).first()
    if not emitter:
        raise ValueError("Emissor fiscal não configurado para a clínica.")

    existing = (
        FiscalDocument.query.filter_by(
            clinic_id=orcamento.clinica_id,
            doc_type=FiscalDocumentType.NFSE,
            source_type="ORCAMENTO",
            source_id=orcamento.id,
        )
        .order_by(FiscalDocument.created_at.desc())
        .first()
    )
    if existing:
        return existing

    payload = build_nfse_payload_from_orcamento(orcamento)
    paciente = payload.get("paciente") or {}
    tomador = payload.get("tomador") or {}
    animal_name = paciente.get("nome")
    tutor_name = tomador.get("nome")
    human_reference = _build_orcamento_human_reference(
        orcamento.descricao,
        animal_name,
        tutor_name,
    )

    document = FiscalDocument(
        emitter_id=emitter.id,
        clinic_id=orcamento.clinica_id,
        doc_type=FiscalDocumentType.NFSE,
        status=FiscalDocumentStatus.DRAFT,
        payload_json=payload,
        source_type="ORCAMENTO",
        source_id=orcamento.id,
        related_type="orcamento",
        related_id=orcamento.id,
        human_reference=human_reference,
        animal_name=animal_name,
        tutor_name=tutor_name,
    )
    db.session.add(document)
    db.session.commit()
    return document


def queue_emit_nfse(document_id: int) -> None:
    document = db.session.get(FiscalDocument, document_id)
    if not document:
        raise ValueError("Documento fiscal não encontrado.")

    if document.status in {
        FiscalDocumentStatus.AUTHORIZED,
        FiscalDocumentStatus.CANCELED,
    }:
        return
    if document.status == FiscalDocumentStatus.PROCESSING:
        return

    if document.status in {
        FiscalDocumentStatus.DRAFT,
        FiscalDocumentStatus.REJECTED,
        FiscalDocumentStatus.FAILED,
    }:
        _transition_status(document, FiscalDocumentStatus.QUEUED, "queued")
        db.session.commit()

    from app.jobs.fiscal_tasks import emit_nfse

    emit_nfse.delay(document_id)


def emit_nfse_sync(document_id: int) -> FiscalDocument:
    document = db.session.get(FiscalDocument, document_id)
    if not document:
        raise ValueError("Documento fiscal não encontrado.")
    if document.status == FiscalDocumentStatus.AUTHORIZED:
        return document
    if document.status in {FiscalDocumentStatus.CANCELED}:
        return document
    if document.status in {FiscalDocumentStatus.REJECTED, FiscalDocumentStatus.FAILED}:
        return document
    try:
        if document.status == FiscalDocumentStatus.DRAFT:
            _transition_status(document, FiscalDocumentStatus.QUEUED, "queued")
        if document.status == FiscalDocumentStatus.QUEUED:
            _transition_status(document, FiscalDocumentStatus.PROCESSING, "sending")
        else:
            _log_event(document, "sending", FiscalDocumentStatus.PROCESSING.value)
        db.session.commit()

        emitter = document.emitter
        if not emitter:
            raise ValueError("Emissor fiscal não configurado.")

        certificate = _get_active_certificate(emitter.id)
        if not certificate:
            raise ValueError("Certificado fiscal A1 não encontrado.")

        payload = _normalize_payload(document, emitter)
        lote_xml = build_lote_xml([payload])
        signed_xml = sign_betha_xml(
            lote_xml,
            pfx_bytes=decrypt_bytes(certificate.pfx_encrypted),
            password=decrypt_text(certificate.pfx_password_encrypted),
        )

        client = _build_betha_client(emitter, certificate)
        response = client.recepcionar_lote_rps({"Xml": signed_xml})

        document.xml_signed = signed_xml
        document.protocol = _extract_xml_value(response.response_xml or "", "Protocolo")
        if response.success:
            _log_event(
                document,
                "recepcionar_lote",
                FiscalDocumentStatus.PROCESSING.value,
                request_xml=_redact_xml(response.request_xml),
                response_xml=_redact_xml(response.response_xml),
                protocol=document.protocol,
            )
        else:
            _transition_status(document, FiscalDocumentStatus.REJECTED, "recepcionar_lote")
            document.error_message = _humanize_betha_error(response.error_message)
            _log_event(
                document,
                "recepcionar_lote",
                FiscalDocumentStatus.REJECTED.value,
                request_xml=_redact_xml(response.request_xml),
                response_xml=_redact_xml(response.response_xml),
                protocol=document.protocol,
                error_message=document.error_message,
            )
        db.session.add(document)
        db.session.commit()
        return document
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Falha ao emitir NFS-e", exc_info=exc)
        _mark_failed(document, _humanize_betha_error(str(exc)), "emitir_nfse")
        db.session.commit()
        return document


def poll_nfse(document_id: int) -> FiscalDocument:
    document = db.session.get(FiscalDocument, document_id)
    if not document:
        raise ValueError("Documento fiscal não encontrado.")
    if document.status == FiscalDocumentStatus.QUEUED:
        _transition_status(document, FiscalDocumentStatus.PROCESSING, "processing")

    try:
        emitter = document.emitter
        certificate = _get_active_certificate(emitter.id) if emitter else None
        if not emitter or not certificate:
            raise ValueError("Configuração fiscal incompleta.")

        client = _build_betha_client(emitter, certificate)
        protocol = document.protocol
        if not protocol:
            raise ValueError("Protocolo não encontrado para consulta.")

        status_response = client.consultar_situacao_lote_rps({"Protocolo": protocol})
        _log_event(
            document,
            "consultar_situacao",
            document.status.value,
            request_xml=_redact_xml(status_response.request_xml),
            response_xml=_redact_xml(status_response.response_xml),
        )
        if not status_response.success:
            _mark_failed(
                document,
                _humanize_betha_error(status_response.error_message),
                "consultar_situacao",
            )
            db.session.add(document)
            db.session.commit()
            return document

        if _is_lote_processado(status_response.response_xml or ""):
            rps_payload = {
                "IdentificacaoRps": {
                    "Numero": document.number,
                    "Serie": document.series,
                    "Tipo": "1",
                },
                "Prestador": {
                    "Cnpj": emitter.cnpj,
                    "InscricaoMunicipal": emitter.inscricao_municipal,
                },
            }
            nfse_response = client.consultar_nfse_por_rps(rps_payload)
            document.nfse_number = _extract_xml_value(nfse_response.response_xml or "", "Numero")
            document.verification_code = _extract_xml_value(
                nfse_response.response_xml or "",
                "CodigoVerificacao",
            )
            document.xml_authorized = nfse_response.response_xml
            if nfse_response.success:
                _transition_status(document, FiscalDocumentStatus.AUTHORIZED, "consultar_nfse")
                document.authorized_at = now_in_brazil()
            else:
                _transition_status(document, FiscalDocumentStatus.REJECTED, "consultar_nfse")
                document.error_message = _humanize_betha_error(nfse_response.error_message)
            _log_event(
                document,
                "consultar_nfse",
                document.status.value,
                request_xml=_redact_xml(nfse_response.request_xml),
                response_xml=_redact_xml(nfse_response.response_xml),
                error_message=document.error_message,
            )
        db.session.add(document)
        db.session.commit()
        return document
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Falha ao consultar NFS-e", exc_info=exc)
        _mark_failed(document, _humanize_betha_error(str(exc)), "consultar_nfse")
        db.session.commit()
        return document


def cancel_nfse_document(document_id: int, reason: Optional[str] = None) -> FiscalDocument:
    document = db.session.get(FiscalDocument, document_id)
    if not document:
        raise ValueError("Documento fiscal não encontrado.")
    if document.status == FiscalDocumentStatus.CANCELED:
        return document

    emitter = document.emitter
    certificate = _get_active_certificate(emitter.id) if emitter else None
    if not emitter or not certificate:
        raise ValueError("Configuração fiscal incompleta.")

    client = _build_betha_client(emitter, certificate)
    payload = {
        "Pedido": {
            "InfPedidoCancelamento": {
                "CodigoCancelamento": reason or "1",
                "IdentificacaoNfse": {
                    "Numero": document.nfse_number,
                    "CpfCnpj": {"Cnpj": emitter.cnpj},
                    "InscricaoMunicipal": emitter.inscricao_municipal,
                    "CodigoMunicipio": emitter.municipio_ibge,
                },
            }
        }
    }
    response = client.cancelar_nfse(payload)
    if response.success:
        _transition_status(document, FiscalDocumentStatus.CANCELED, "cancelar_nfse")
        document.canceled_at = now_in_brazil()
    else:
        _transition_status(document, FiscalDocumentStatus.REJECTED, "cancelar_nfse")
        document.error_message = _humanize_betha_error(response.error_message)
    _log_event(
        document,
        "cancelar_nfse",
        document.status.value,
        request_xml=_redact_xml(response.request_xml),
        response_xml=_redact_xml(response.response_xml),
        error_message=document.error_message,
    )
    db.session.add(document)
    db.session.commit()
    return document


def _normalize_payload(document: FiscalDocument, emitter: FiscalEmitter) -> dict[str, Any]:
    payload = dict(document.payload_json or {})
    payload.setdefault("rps", {})
    payload["rps"].setdefault("numero", document.number)
    payload["rps"].setdefault("serie", document.series)
    payload["rps"].setdefault("data_emissao", datetime.now().isoformat())

    payload.setdefault("prestador", {})
    payload["prestador"].setdefault("cnpj", emitter.cnpj)
    payload["prestador"].setdefault("im", emitter.inscricao_municipal)
    payload["prestador"].setdefault("endereco", emitter.endereco_json or {})

    return payload


def _humanize_betha_error(message: str | None) -> str:
    if not message:
        return "Não foi possível emitir a NFS-e no momento."
    text = message.lower()
    if any(key in text for key in ["certificado", "certificate", "pfx", "pkcs"]):
        return "Certificado digital vencido ou inválido."
    if "timeout" in text or "timed out" in text or "tempo esgotado" in text:
        return "Prefeitura indisponível, tentaremos novamente."
    if "schema" in text or "xsd" in text:
        return "Dados fiscais incompletos."
    if "servico" in text or "serviço" in text or "item" in text:
        return "Serviço não configurado para emissão fiscal."
    return "Não foi possível emitir a NFS-e no momento."


def _get_active_certificate(emitter_id: int) -> FiscalCertificate | None:
    return (
        FiscalCertificate.query
        .filter_by(emitter_id=emitter_id)
        .order_by(FiscalCertificate.created_at.desc())
        .first()
    )


def _build_betha_client(emitter: FiscalEmitter, certificate: FiscalCertificate) -> BethaNfseClient:
    wsdl_map = current_app.config.get("NFSE_BETHA_WSDL", {})
    wsdl_config = BethaWsdlConfig(
        recepcionar_lote_rps=wsdl_map.get("recepcionar_lote_rps", ""),
        consultar_situacao_lote_rps=wsdl_map.get("consultar_situacao_lote_rps", ""),
        consultar_nfse_por_rps=wsdl_map.get("consultar_nfse_por_rps", ""),
        cancelar_nfse=wsdl_map.get("cancelar_nfse", ""),
    )
    if not all(wsdl_config.__dict__.values()):
        raise ValueError("WSDL Betha não configurado.")

    return BethaNfseClient(
        wsdl_config=wsdl_config,
        pfx_bytes=decrypt_bytes(certificate.pfx_encrypted),
        pfx_password=decrypt_text(certificate.pfx_password_encrypted),
    )


def _can_transition_status(
    current: FiscalDocumentStatus,
    target: FiscalDocumentStatus,
) -> bool:
    if current == target:
        return True
    transitions = {
        FiscalDocumentStatus.DRAFT: {FiscalDocumentStatus.QUEUED},
        FiscalDocumentStatus.QUEUED: {FiscalDocumentStatus.PROCESSING, FiscalDocumentStatus.FAILED},
        FiscalDocumentStatus.PROCESSING: {
            FiscalDocumentStatus.AUTHORIZED,
            FiscalDocumentStatus.REJECTED,
            FiscalDocumentStatus.FAILED,
        },
        FiscalDocumentStatus.REJECTED: {FiscalDocumentStatus.QUEUED, FiscalDocumentStatus.FAILED},
        FiscalDocumentStatus.FAILED: {FiscalDocumentStatus.QUEUED},
        FiscalDocumentStatus.AUTHORIZED: {FiscalDocumentStatus.CANCELED},
        FiscalDocumentStatus.CANCELED: set(),
    }
    return target in transitions.get(current, set())


def _transition_status(
    document: FiscalDocument,
    target: FiscalDocumentStatus,
    event_type: str,
) -> None:
    current = document.status
    if current == target:
        return
    if not _can_transition_status(current, target):
        raise ValueError(f"Transição fiscal inválida: {current.value} -> {target.value}")
    document.status = target
    _log_event(document, event_type, target.value)


def _mark_failed(document: FiscalDocument, error_message: str, event_type: str) -> None:
    if document.status != FiscalDocumentStatus.FAILED and _can_transition_status(
        document.status,
        FiscalDocumentStatus.FAILED,
    ):
        document.status = FiscalDocumentStatus.FAILED
    document.error_message = error_message
    _log_event(document, event_type, document.status.value, error_message=error_message)


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
        if node is not None and node.text:
            return node.text
    except Exception:  # noqa: BLE001
        return None
    return None


def _is_lote_processado(xml: str) -> bool:
    if not xml:
        return False
    texto = (xml or "").lower()
    return any(key in texto for key in ["processado", "autorizado", "sucesso"]) or "situacao" in texto


def _redact_xml(xml: str | None) -> str | None:
    if not xml:
        return xml
    try:
        root = etree.fromstring(xml.encode("utf-8"))
        for tag in ["Cpf", "Cnpj", "InscricaoMunicipal", "Senha"]:
            for node in root.findall(f".//{tag}"):
                if node.text:
                    node.text = "***"
        return etree.tostring(root, encoding="unicode")
    except Exception:  # noqa: BLE001
        return xml


def build_nfse_payload_from_appointment(appointment: Appointment) -> dict[str, Any]:
    consulta = appointment.consulta if appointment else None
    tomador_nome = None
    if appointment.tutor:
        tomador_nome = appointment.tutor.name
    elif appointment.animal and appointment.animal.owner:
        tomador_nome = appointment.animal.owner.name

    servico_desc = "Atendimento veterinário"
    if consulta and consulta.descricao:
        servico_desc = consulta.descricao

    valor_total = 0
    if consulta and getattr(consulta, "orcamento_items", None):
        valor_total = sum((item.valor for item in consulta.orcamento_items), start=0)

    payload = {
        "prestador": {
            "cnpj": appointment.clinica.cnpj if appointment.clinica else None,
            "im": appointment.clinica.inscricao_municipal if appointment.clinica else None,
            "endereco": appointment.clinica.endereco_json if appointment.clinica else {},
        },
        "tomador": {
            "cpf_cnpj": appointment.tutor.cpf if appointment.tutor else None,
            "nome": tomador_nome,
        },
        "servico": {
            "item_lista": "0000",
            "descricao": servico_desc,
            "valor": valor_total,
        },
        "rps": {},
    }
    if appointment.clinica and appointment.clinica.municipio_ibge:
        payload["tomador"].setdefault("endereco", {"codigo_municipio": appointment.clinica.municipio_ibge})

    payload["source"] = {
        "appointment_id": appointment.id,
        "consulta_id": appointment.consulta_id,
    }
    return payload


def build_nfse_payload_from_orcamento(orcamento: Orcamento) -> dict[str, Any]:
    consulta = orcamento.consulta
    animal = consulta.animal if consulta else None
    tomador = animal.owner if animal else None
    items = [
        {
            "id": item.id,
            "descricao": item.descricao,
            "valor": float(item.valor or 0),
            "payer_type": item.effective_payer_type,
        }
        for item in orcamento.items
    ]

    return {
        "id": orcamento.id,
        "consulta_id": orcamento.consulta_id,
        "descricao": orcamento.descricao,
        "valor_total": float(orcamento.total or 0),
        "itens": items,
        "paciente": (
            {
                "id": animal.id,
                "nome": animal.name,
                "especie": animal.species,
                "raca": animal.breed,
            }
            if animal
            else None
        ),
        "tomador": (
            {
                "id": tomador.id,
                "nome": tomador.name,
                "cpf_cnpj": tomador.cpf,
                "email": tomador.email,
                "telefone": tomador.phone,
                "endereco_texto": tomador.address,
            }
            if tomador
            else None
        ),
    }


def _build_orcamento_human_reference(
    descricao: str | None,
    animal_name: str | None,
    tutor_name: str | None,
) -> str:
    base = (descricao or "Orçamento").strip()
    reference = base
    if animal_name:
        reference = f"{reference} - {animal_name}"
    if tutor_name:
        reference = f"{reference} (tutor {tutor_name})"
    return reference
