"""Rotinas recorrentes de manutenção fiscal."""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from sqlalchemy import func

from app.jobs.celery_app import celery_app
from extensions import db
from models import (
    ClinicNotification,
    FiscalCertificate,
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalDocumentType,
    FiscalEmitter,
    FiscalEvent,
)
from services.fiscal.nfse_service import emit_nfse_sync, poll_nfse
from services.fiscal.nfe_service import emit_nfe_sync, poll_nfe as poll_nfe_sync
from time_utils import now_in_brazil, utcnow

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, minimum)


FAILED_LOOKBACK_DAYS = _env_int("FISCAL_FAILED_LOOKBACK_DAYS", 3, 1)
FAILED_MAX_RETRIES = _env_int("FISCAL_FAILED_MAX_RETRIES", 3, 1)
FAILED_BATCH_LIMIT = _env_int("FISCAL_FAILED_BATCH_LIMIT", 50, 1)
PROCESSING_STALE_MINUTES = _env_int("FISCAL_PROCESSING_STALE_MINUTES", 30, 5)
PROCESSING_BATCH_LIMIT = _env_int("FISCAL_PROCESSING_BATCH_LIMIT", 50, 1)
CERTIFICATE_WARNING_DAYS = {30, 15, 7}
MAINTENANCE_RETRY_EVENT = "maintenance_retry"


_retry_kwargs = {
    "autoretry_for": (Exception,),
    "retry_backoff": True,
    "retry_backoff_max": 300,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 3},
}


def _log_maintenance_event(document: FiscalDocument, message: str) -> None:
    db.session.add(
        FiscalEvent(
            document_id=document.id,
            event_type=MAINTENANCE_RETRY_EVENT,
            status=document.status.value,
            error_message=message,
        )
    )


def _retry_failed_documents() -> int:
    lookback_start = utcnow() - timedelta(days=FAILED_LOOKBACK_DAYS)
    documents = (
        FiscalDocument.query
        .filter(FiscalDocument.status == FiscalDocumentStatus.FAILED)
        .filter(FiscalDocument.updated_at >= lookback_start)
        .order_by(FiscalDocument.updated_at.asc())
        .limit(FAILED_BATCH_LIMIT)
        .all()
    )
    if not documents:
        return 0

    retry_counts = dict(
        db.session.query(FiscalEvent.document_id, func.count(FiscalEvent.id))
        .filter(FiscalEvent.document_id.in_([doc.id for doc in documents]))
        .filter(FiscalEvent.event_type == MAINTENANCE_RETRY_EVENT)
        .group_by(FiscalEvent.document_id)
        .all()
    )

    processed = 0
    for document in documents:
        attempts = retry_counts.get(document.id, 0)
        if attempts >= FAILED_MAX_RETRIES:
            continue
        message = f"Retry automático {attempts + 1}/{FAILED_MAX_RETRIES}."
        _log_maintenance_event(document, message)
        db.session.commit()
        try:
            if document.doc_type == FiscalDocumentType.NFSE:
                emit_nfse_sync(document.id)
            else:
                emit_nfe_sync(document.id)
            processed += 1
        except Exception as exc:  # noqa: BLE001 - continuar com demais documentos
            logger.exception(
                "Falha ao reprocessar documento fiscal %s: %s",
                document.id,
                exc,
            )
    return processed


def _poll_stale_processing_documents() -> int:
    threshold = utcnow() - timedelta(minutes=PROCESSING_STALE_MINUTES)
    documents = (
        FiscalDocument.query
        .filter(FiscalDocument.status == FiscalDocumentStatus.PROCESSING)
        .filter(FiscalDocument.updated_at <= threshold)
        .order_by(FiscalDocument.updated_at.asc())
        .limit(PROCESSING_BATCH_LIMIT)
        .all()
    )

    processed = 0
    for document in documents:
        try:
            if document.doc_type == FiscalDocumentType.NFSE:
                poll_nfse(document.id)
            else:
                poll_nfe_sync(document.id)
            processed += 1
        except Exception as exc:  # noqa: BLE001 - continuar com demais documentos
            logger.exception(
                "Falha ao consultar documento fiscal %s: %s",
                document.id,
                exc,
            )
    return processed


def _ensure_certificate_notifications(reference: date) -> int:
    month_start = reference.replace(day=1)
    certificates = (
        db.session.query(FiscalCertificate, FiscalEmitter)
        .join(FiscalEmitter, FiscalCertificate.emitter_id == FiscalEmitter.id)
        .filter(FiscalCertificate.valid_to.is_not(None))
        .all()
    )

    active_markers: set[str] = set()
    created = 0
    for certificate, emitter in certificates:
        if not certificate.valid_to:
            continue
        days_left = (certificate.valid_to.date() - reference).days
        if days_left not in CERTIFICATE_WARNING_DAYS or days_left < 0:
            continue
        marker = f"[FiscalCertificate:{certificate.id}:{days_left}]"
        active_markers.add(marker)
        title = "Certificado fiscal a vencer"
        type_ = "danger" if days_left <= 7 else "warning"
        message = (
            f"{marker} Certificado do emissor {emitter.razao_social} "
            f"(CNPJ {emitter.cnpj}) vence em {days_left} dia(s) "
            f"({certificate.valid_to.strftime('%d/%m/%Y')})."
        )
        existing = (
            ClinicNotification.query.filter_by(
                clinic_id=emitter.clinic_id,
                month=month_start,
                title=title,
            )
            .filter(ClinicNotification.message.like(f"{marker}%"))
            .one_or_none()
        )
        if existing:
            if existing.message != message:
                existing.message = message
            if existing.resolved:
                existing.resolved = False
                existing.resolution_date = None
            continue
        db.session.add(
            ClinicNotification(
                clinic_id=emitter.clinic_id,
                month=month_start,
                title=title,
                message=message,
                type=type_,
                created_at=utcnow(),
            )
        )
        created += 1

    stale_notices = (
        ClinicNotification.query.filter_by(
            month=month_start,
            title="Certificado fiscal a vencer",
            resolved=False,
        )
        .filter(ClinicNotification.message.like("[FiscalCertificate:%"))
        .all()
    )
    for notice in stale_notices:
        marker = (notice.message or "").split(" ")[0]
        if marker not in active_markers:
            notice.resolved = True
            notice.resolution_date = utcnow()

    db.session.commit()
    return created


@celery_app.task(name="jobs.fiscal_maintenance", **_retry_kwargs)
def run_fiscal_maintenance() -> dict[str, int]:
    reference_date = now_in_brazil().date()
    failed_reprocessed = _retry_failed_documents()
    processing_polled = _poll_stale_processing_documents()
    certificates_alerted = _ensure_certificate_notifications(reference_date)
    logger.info(
        "Manutenção fiscal: %s reprocessados, %s consultados, %s alertas emitidos.",
        failed_reprocessed,
        processing_polled,
        certificates_alerted,
    )
    return {
        "failed_reprocessed": failed_reprocessed,
        "processing_polled": processing_polled,
        "certificates_alerted": certificates_alerted,
    }
