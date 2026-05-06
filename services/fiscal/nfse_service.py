"""Servico de emissao NFS-e (Betha/Orlandia e NFS-e Nacional/PBH)."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

from flask import current_app

from lxml import etree

# Parse seguro de XML externo (resposta Betha / prefeitura). Mantemos lxml
# para serialização/XPath, mas entrada parseamos via helper hardened contra XXE.
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
    Orcamento,
)
from providers.nfse.betha import build_lote_xml, sign_betha_xml
from providers.nfse.betha.client import BethaNfseClient
from providers.nfse.betha.client import BethaWsdlConfig
from providers.nfse.nacional import (
    NacionalNfseClient,
    NacionalNfseConfig,
    build_cancel_event_xml,
    build_dps_id,
    build_dps_xml,
    sign_nacional_xml,
)
from providers.nfse.nacional.client import NacionalNfseResponse
from security.crypto import decrypt_bytes, decrypt_text
from security.redact import redact_sensitive_text, redact_xml
from services.fiscal.numbering import NumberingReservationError, reserve_next_number
from time_utils import now_in_brazil


class FiscalXmlParseError(ValueError):
    """Raised when an external fiscal XML response cannot be parsed safely."""


def create_nfse_document(
    related_type: str,
    related_id: int,
    emitter_id: int,
    payload: dict[str, Any],
) -> FiscalDocument:
    emitter = db.session.get(FiscalEmitter, emitter_id)
    if not emitter:
        raise ValueError("Emissor fiscal não encontrado.")

    _ensure_related_clinic_consistency(related_type, related_id, emitter.clinic_id)

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


def create_manual_nfse_document(
    emitter_id: int,
    payload: dict[str, Any],
) -> FiscalDocument:
    emitter = db.session.get(FiscalEmitter, emitter_id)
    if not emitter:
        raise ValueError("Emissor fiscal nao encontrado.")

    series = str((payload.get("rps") or {}).get("serie") or payload.get("serie") or "1")
    number = reserve_next_number(emitter.id, FiscalDocumentType.NFSE, series)
    payload = dict(payload or {})
    payload.setdefault("rps", {})
    payload["rps"]["numero"] = number
    payload["rps"]["serie"] = series

    tomador = payload.get("tomador") or {}
    servico = payload.get("servico") or {}
    document = FiscalDocument(
        emitter_id=emitter.id,
        clinic_id=emitter.clinic_id,
        doc_type=FiscalDocumentType.NFSE,
        status=FiscalDocumentStatus.QUEUED,
        series=series,
        number=number,
        payload_json=payload,
        source_type="MANUAL_NFSE",
        related_type="manual_nfse",
        human_reference=servico.get("descricao") or payload.get("descricao") or "NFS-e manual",
        tutor_name=tomador.get("nome"),
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


def queue_emit_nfse(document_id: int, clinic_id: int | None = None) -> None:
    document = db.session.get(FiscalDocument, document_id)
    if not document:
        raise ValueError("Documento fiscal não encontrado.")
    if clinic_id is not None and document.clinic_id != clinic_id:
        _audit_scope_violation(
            document,
            action="queue_emit_nfse",
            expected_clinic_id=clinic_id,
            emitter_clinic_id=document.emitter.clinic_id if document.emitter else None,
        )
        raise ValueError("Documento fiscal fora do escopo da clínica.")

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

    emit_nfse.delay(document_id, clinic_id=document.clinic_id)


def emit_nfse_sync(document_id: int, clinic_id: int | None = None) -> FiscalDocument:
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
        _ensure_document_scope(document, emitter, "emit_nfse_sync", clinic_id)

        certificate = _get_active_certificate(emitter.id)
        if not certificate:
            raise ValueError("Certificado fiscal A1 não encontrado.")

        payload = _normalize_payload(document, emitter)
        if _is_nacional_nfse(emitter, payload):
            _emit_nfse_nacional(document, emitter, certificate, payload)
            db.session.add(document)
            db.session.commit()
            return document

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
    except (ValueError, RuntimeError, NumberingReservationError, FiscalXmlParseError) as exc:
        current_app.logger.warning("Falha esperada ao emitir NFS-e: %s", exc, exc_info=True)
        _mark_failed(
            document,
            _humanize_betha_error(str(exc)),
            "emitir_nfse",
            error_code=type(exc).__name__,
            error_details=str(exc),
        )
        db.session.commit()
        return document
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Falha inesperada ao emitir NFS-e")
        _mark_failed(
            document,
            _humanize_betha_error(str(exc)),
            "emitir_nfse",
            error_code=type(exc).__name__,
            error_details=repr(exc),
        )
        db.session.commit()
        return document


def poll_nfse(document_id: int, clinic_id: int | None = None) -> FiscalDocument:
    document = db.session.get(FiscalDocument, document_id)
    if not document:
        raise ValueError("Documento fiscal não encontrado.")
    if document.status == FiscalDocumentStatus.QUEUED:
        _transition_status(document, FiscalDocumentStatus.PROCESSING, "processing")

    try:
        emitter = document.emitter
        if not emitter:
            raise ValueError("Configuração fiscal incompleta.")
        _ensure_document_scope(document, emitter, "poll_nfse", clinic_id)
        certificate = _get_active_certificate(emitter.id)
        if not certificate:
            raise ValueError("Configuração fiscal incompleta.")

        payload = _normalize_payload(document, emitter)
        if _is_nacional_nfse(emitter, payload):
            _poll_nfse_nacional(document, emitter, certificate, payload)
            db.session.add(document)
            db.session.commit()
            return document

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
                from services.finance import sync_receivable_from_nfse
                sync_receivable_from_nfse(document, commit=False)
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
    except (ValueError, RuntimeError, FiscalXmlParseError) as exc:
        current_app.logger.warning("Falha esperada ao consultar NFS-e: %s", exc, exc_info=True)
        _mark_failed(
            document,
            _humanize_betha_error(str(exc)),
            "consultar_nfse",
            error_code=type(exc).__name__,
            error_details=str(exc),
        )
        db.session.commit()
        return document
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Falha inesperada ao consultar NFS-e")
        _mark_failed(
            document,
            _humanize_betha_error(str(exc)),
            "consultar_nfse",
            error_code=type(exc).__name__,
            error_details=repr(exc),
        )
        db.session.commit()
        return document


def cancel_nfse_document(
    document_id: int,
    reason: Optional[str] = None,
    clinic_id: int | None = None,
) -> FiscalDocument:
    document = db.session.get(FiscalDocument, document_id)
    if not document:
        raise ValueError("Documento fiscal não encontrado.")
    if document.status == FiscalDocumentStatus.CANCELED:
        return document

    emitter = document.emitter
    if not emitter:
        raise ValueError("Configuração fiscal incompleta.")
    _ensure_document_scope(document, emitter, "cancel_nfse_document", clinic_id)
    certificate = _get_active_certificate(emitter.id)
    if not certificate:
        raise ValueError("Configuração fiscal incompleta.")

    payload = _normalize_payload(document, emitter)
    if _is_nacional_nfse(emitter, payload):
        _cancel_nfse_nacional(document, emitter, certificate, reason)
        db.session.add(document)
        db.session.commit()
        return document

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
    payload["rps"].setdefault("data_emissao", now_in_brazil().isoformat())

    payload.setdefault("prestador", {})
    payload["prestador"].setdefault("cnpj", emitter.cnpj)
    payload["prestador"].setdefault("im", emitter.inscricao_municipal)
    payload["prestador"].setdefault("nome", emitter.razao_social)
    payload["prestador"].setdefault("endereco", emitter.endereco_json or {})
    payload["prestador"].setdefault("regime_tributario", emitter.regime_tributario)

    clinic = emitter.clinic
    if clinic is not None:
        payload.setdefault("municipio_nfse", getattr(clinic, "municipio_nfse", None))
        payload.setdefault("municipio_ibge", emitter.municipio_ibge or _clinic_field(clinic, "municipio_ibge"))
        payload.setdefault("codigo_servico", _clinic_field(clinic, "codigo_servico"))
        payload.setdefault("aliquota_iss", _clinic_field(clinic, "aliquota_iss"))
        payload.setdefault("regime_tributario", emitter.regime_tributario or _clinic_field(clinic, "regime_tributario"))
        payload["prestador"].setdefault("regime_tributario", emitter.regime_tributario or _clinic_field(clinic, "regime_tributario"))
        payload["prestador"].setdefault("telefone", getattr(clinic, "telefone", None))
        payload["prestador"].setdefault("email", getattr(clinic, "email", None))
        if not payload["prestador"].get("endereco"):
            payload["prestador"]["endereco"] = _clinic_address_payload(clinic, emitter)

    payload.setdefault("servico", {})
    service_code = payload.get("codigo_servico")
    if service_code and payload["servico"].get("item_lista") in (None, "", "0000"):
        payload["servico"]["item_lista"] = service_code
    payload["servico"].setdefault("aliquota_iss", payload.get("aliquota_iss"))

    return payload


def _clinic_field(clinic: Any, field: str, default: Any = None) -> Any:
    if clinic is None:
        return default
    return getattr(clinic, field, default)


def _clinic_address_payload(clinic: Any, emitter: FiscalEmitter) -> dict[str, Any]:
    endereco = emitter.endereco_json or {}
    if endereco:
        return endereco
    return {
        "logradouro": _clinic_field(clinic, "endereco"),
        "codigo_municipio": emitter.municipio_ibge,
        "uf": emitter.uf,
    }


def _normalize_provider_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _is_nacional_nfse(emitter: FiscalEmitter, payload: dict[str, Any] | None = None) -> bool:
    payload = payload or {}
    provider = _normalize_provider_text(payload.get("provider") or payload.get("provedor_nfse"))
    municipio_nfse = _normalize_provider_text(payload.get("municipio_nfse") or "")
    municipio_ibge = re.sub(r"\D+", "", str(payload.get("municipio_ibge") or emitter.municipio_ibge or ""))
    if provider in {"nacional", "nfse_nacional", "pbh", "belo_horizonte"}:
        return True
    if municipio_ibge == "3106200":
        return True
    return municipio_nfse in {"bh", "pbh", "belo_horizonte", "belo_horizonte_mg"}


def _nacional_xml_options() -> dict[str, str]:
    config = current_app.config.get("NFSE_NACIONAL_XML", {})
    return {
        "ambiente": str(config.get("ambiente") or "2"),
        "versao": str(config.get("versao") or "1.01"),
        "ver_aplic": str(config.get("ver_aplic") or "Petorlandia-1.0"),
        "signature_algorithm": str(config.get("signature_algorithm") or "rsa-sha1"),
        "digest_algorithm": str(config.get("digest_algorithm") or "sha1"),
    }


def _build_nacional_client(
    certificate: FiscalCertificate,
) -> NacionalNfseClient:
    api_config = current_app.config.get("NFSE_NACIONAL_API", {})
    config = NacionalNfseConfig(
        base_url=api_config.get("base_url") or NacionalNfseConfig.base_url,
        environment=api_config.get("environment") or "producao_restrita",
        production_base_url=api_config.get("production_base_url")
        or NacionalNfseConfig.production_base_url,
        timeout=int(api_config.get("timeout") or 30),
        nfse_path=api_config.get("nfse_path") or "/nfse",
        dps_path=api_config.get("dps_path") or "/dps/{id}",
        eventos_path=api_config.get("eventos_path") or "/nfse/{chave_acesso}/eventos",
    )
    return NacionalNfseClient(
        config,
        pfx_bytes=decrypt_bytes(certificate.pfx_encrypted),
        pfx_password=decrypt_text(certificate.pfx_password_encrypted),
    )


def _document_dps_id(document: FiscalDocument, emitter: FiscalEmitter, payload: dict[str, Any]) -> str:
    rps = payload.get("rps") or {}
    prestador = payload.get("prestador") or {}
    return build_dps_id(
        payload.get("municipio_ibge") or emitter.municipio_ibge or "3106200",
        prestador.get("cnpj") or emitter.cnpj,
        rps.get("serie") or document.series or "1",
        rps.get("numero") or document.number,
    )


def _apply_nacional_response(document: FiscalDocument, response: NacionalNfseResponse) -> None:
    document.protocol = response.protocol or document.protocol
    document.access_key = response.access_key or document.access_key
    document.nfse_number = response.nfse_number or document.nfse_number
    document.verification_code = response.verification_code or document.verification_code
    if response.response_xml:
        document.xml_authorized = response.response_xml


def _emit_nfse_nacional(
    document: FiscalDocument,
    emitter: FiscalEmitter,
    certificate: FiscalCertificate,
    payload: dict[str, Any],
) -> None:
    options = _nacional_xml_options()
    dps_xml = build_dps_xml(
        payload,
        ambiente=options["ambiente"],
        versao=options["versao"],
        ver_aplic=options["ver_aplic"],
    )
    signed_xml = sign_nacional_xml(
        dps_xml,
        pfx_bytes=decrypt_bytes(certificate.pfx_encrypted),
        password=decrypt_text(certificate.pfx_password_encrypted),
        signature_algorithm=options["signature_algorithm"],
        digest_algorithm=options["digest_algorithm"],
    )
    client = _build_nacional_client(certificate)
    response = client.emitir_dps(signed_xml)

    document.xml_signed = signed_xml
    document.protocol = response.protocol or _document_dps_id(document, emitter, payload)
    _apply_nacional_response(document, response)

    if response.success:
        if response.response_xml or response.access_key or response.nfse_number:
            _transition_status(document, FiscalDocumentStatus.AUTHORIZED, "emitir_nfse_nacional")
            document.authorized_at = now_in_brazil()
            from services.finance import sync_receivable_from_nfse

            sync_receivable_from_nfse(document, commit=False)
        _log_event(
            document,
            "emitir_nfse_nacional",
            document.status.value,
            request_xml=_redact_xml(signed_xml),
            response_xml=_redact_xml(response.response_xml),
            protocol=document.protocol,
        )
        return

    _transition_status(document, FiscalDocumentStatus.REJECTED, "emitir_nfse_nacional")
    document.error_message = _humanize_nfse_error(response.error_message)
    _log_event(
        document,
        "emitir_nfse_nacional",
        FiscalDocumentStatus.REJECTED.value,
        request_xml=_redact_xml(signed_xml),
        response_xml=_redact_xml(response.response_xml),
        protocol=document.protocol,
        error_message=document.error_message,
    )


def _poll_nfse_nacional(
    document: FiscalDocument,
    emitter: FiscalEmitter,
    certificate: FiscalCertificate,
    payload: dict[str, Any],
) -> None:
    client = _build_nacional_client(certificate)
    if document.access_key:
        response = client.consultar_nfse(document.access_key)
    else:
        response = client.consultar_dps(_document_dps_id(document, emitter, payload))
        if response.success and response.access_key and not response.response_xml:
            response = client.consultar_nfse(response.access_key)

    _apply_nacional_response(document, response)
    if response.success and (response.response_xml or response.access_key):
        if document.status != FiscalDocumentStatus.AUTHORIZED:
            _transition_status(document, FiscalDocumentStatus.AUTHORIZED, "consultar_nfse_nacional")
        document.authorized_at = document.authorized_at or now_in_brazil()
        from services.finance import sync_receivable_from_nfse

        sync_receivable_from_nfse(document, commit=False)
    elif not response.success:
        document.error_message = _humanize_nfse_error(response.error_message)
    _log_event(
        document,
        "consultar_nfse_nacional",
        document.status.value,
        response_xml=_redact_xml(response.response_xml),
        protocol=document.protocol,
        error_message=document.error_message if not response.success else None,
    )


def _cancel_nfse_nacional(
    document: FiscalDocument,
    emitter: FiscalEmitter,
    certificate: FiscalCertificate,
    reason: str | None,
) -> None:
    access_key = document.access_key
    if not access_key:
        raise ValueError("Chave de acesso da NFS-e nao encontrada para cancelamento.")

    options = _nacional_xml_options()
    reason_code = reason if reason in {"1", "2", "9"} else "9"
    reason_description = (
        "Erro na emissao"
        if reason in {None, "", "1"}
        else ("Servico nao prestado" if reason == "2" else str(reason))
    )
    event_xml = build_cancel_event_xml(
        access_key,
        emitter.cnpj,
        reason_code=reason_code,
        reason_description=reason_description,
        ambiente=options["ambiente"],
        versao=options["versao"],
        ver_aplic=options["ver_aplic"],
    )
    signed_event_xml = sign_nacional_xml(
        event_xml,
        pfx_bytes=decrypt_bytes(certificate.pfx_encrypted),
        password=decrypt_text(certificate.pfx_password_encrypted),
        node_tag="infPedReg",
        signature_algorithm=options["signature_algorithm"],
        digest_algorithm=options["digest_algorithm"],
    )
    client = _build_nacional_client(certificate)
    response = client.registrar_evento(access_key, signed_event_xml)

    if response.success:
        _transition_status(document, FiscalDocumentStatus.CANCELED, "cancelar_nfse_nacional")
        document.canceled_at = now_in_brazil()
        document.error_message = None
    else:
        document.error_message = _humanize_nfse_error(response.error_message)
    _log_event(
        document,
        "cancelar_nfse_nacional",
        document.status.value,
        request_xml=_redact_xml(signed_event_xml),
        response_xml=_redact_xml(response.response_xml),
        error_message=None if response.success else document.error_message,
    )


def _ensure_related_clinic_consistency(
    related_type: str,
    related_id: int,
    emitter_clinic_id: int | None,
) -> None:
    if not emitter_clinic_id:
        raise ValueError("Emissor fiscal sem clínica associada.")

    related_clinic_id = None
    if related_type == "appointment":
        appointment = db.session.get(Appointment, related_id)
        if not appointment:
            raise ValueError("Atendimento não encontrado.")
        related_clinic_id = appointment.clinica_id
    elif related_type == "orcamento":
        orcamento = db.session.get(Orcamento, related_id)
        if not orcamento:
            raise ValueError("Orçamento não encontrado.")
        related_clinic_id = orcamento.clinica_id

    if related_clinic_id is not None and related_clinic_id != emitter_clinic_id:
        raise ValueError("Emissor fiscal não pertence à clínica do documento.")


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


def _humanize_nfse_error(message: str | None) -> str:
    if not message:
        return "Não foi possível emitir a NFS-e no momento."
    text = message.lower()
    if "dps" in text and ("duplic" in text or "ja existe" in text or "já existe" in text):
        return "DPS já enviada para esta numeração."
    if "certificado" in text or "certificate" in text or "tls" in text:
        return "Certificado digital vencido ou inválido."
    if "credenc" in text or "autoriza" in text or "convenio" in text or "convênio" in text:
        return "Prestador ainda não autorizado para emissão no município."
    if "codigo" in text and "serv" in text:
        return "Código de serviço não configurado para a PBH/NFS-e Nacional."
    if "timeout" in text or "timed out" in text or "tempo esgotado" in text:
        return "Ambiente NFS-e Nacional indisponível, tentaremos novamente."
    return message[:280]


def _ensure_document_scope(
    document: FiscalDocument,
    emitter: FiscalEmitter,
    action: str,
    expected_clinic_id: int | None,
) -> None:
    if document.clinic_id != emitter.clinic_id:
        _audit_scope_violation(
            document,
            action=action,
            expected_clinic_id=expected_clinic_id,
            emitter_clinic_id=emitter.clinic_id,
        )
        raise ValueError("Documento fiscal fora do escopo da clínica.")
    if expected_clinic_id is not None and document.clinic_id != expected_clinic_id:
        _audit_scope_violation(
            document,
            action=action,
            expected_clinic_id=expected_clinic_id,
            emitter_clinic_id=emitter.clinic_id,
        )
        raise ValueError("Documento fiscal fora do escopo da clínica.")


def _audit_scope_violation(
    document: FiscalDocument,
    action: str,
    expected_clinic_id: int | None,
    emitter_clinic_id: int | None,
) -> None:
    message_parts = [
        f"Acesso fora do escopo bloqueado em {action}.",
        f"document_clinic_id={document.clinic_id}",
    ]
    if expected_clinic_id is not None:
        message_parts.append(f"expected_clinic_id={expected_clinic_id}")
    if emitter_clinic_id is not None:
        message_parts.append(f"emitter_clinic_id={emitter_clinic_id}")
    _log_event(
        document,
        "scope_violation",
        document.status.value,
        error_message=" ".join(message_parts),
    )
    db.session.commit()


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


def _mark_failed(
    document: FiscalDocument,
    error_message: str,
    event_type: str,
    *,
    error_code: str | None = None,
    error_details: str | None = None,
) -> None:
    if document.status != FiscalDocumentStatus.FAILED and _can_transition_status(
        document.status,
        FiscalDocumentStatus.FAILED,
    ):
        document.status = FiscalDocumentStatus.FAILED
    document.error_message = error_message
    if error_code:
        document.error_code = error_code
    event_error = error_message
    if error_details:
        event_error = f"{error_message} | causa={error_details}"
    _log_event(document, event_type, document.status.value, error_message=event_error)


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
            for candidate in root.iter():
                local = str(candidate.tag).split("}", 1)[-1]
                if local == tag:
                    node = candidate
                    break
        if node is not None and node.text:
            return node.text
    except etree.XMLSyntaxError as exc:
        raise FiscalXmlParseError(f"XML fiscal malformado ao buscar tag {tag}.") from exc
    except Exception as exc:  # noqa: BLE001
        # Inclui os erros de defusedxml (entities forbidden etc.) e qualquer
        # outra falha inesperada. Log explícito pra auditoria.
        current_app.logger.warning(
            "Falha ao extrair tag %s do XML de resposta: %s", tag, exc
        )
        raise FiscalXmlParseError(f"XML fiscal inseguro ou invalido ao buscar tag {tag}.") from exc
    return None


def _is_lote_processado(xml: str) -> bool:
    if not xml:
        return False
    texto = (xml or "").lower()
    return any(key in texto for key in ["processado", "autorizado", "sucesso"]) or "situacao" in texto


def _redact_xml(xml: str | None) -> str | None:
    """Delega para security.redact.redact_xml.

    Mantido como função local para não tocar nos call-sites
    (`_log_event(response_xml=_redact_xml(...))`). A cobertura agora inclui
    CPF/CNPJ mascarados (123.456.789-00 / 12.345.678/0001-90), chave NF-e
    de 44 dígitos, e redação em nodos de texto não-sensíveis (ex:
    InfoAdicional, Mensagem). Ver security/redact.py.
    """
    return redact_xml(xml)


def _redact_xml_text(xml: str | None) -> str | None:
    """Versão só-texto (fallback para strings que não são XML válido).
    Delega pro módulo compartilhado — agora cobre CPF/CNPJ com e sem
    máscara, chave NF-e de 44 dígitos, e tokens em tags conhecidas."""
    if not xml:
        return xml
    return redact_sensitive_text(xml)


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
