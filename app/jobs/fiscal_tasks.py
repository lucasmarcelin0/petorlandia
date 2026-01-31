"""Celery tasks for fiscal document processing."""
from __future__ import annotations

import logging

from app.jobs.celery_app import celery_app
from extensions import db
from models import FiscalDocument, FiscalDocumentStatus

logger = logging.getLogger(__name__)


def _mark_processing(document_id: int) -> FiscalDocument | None:
    document = db.session.get(FiscalDocument, document_id)
    if not document:
        logger.warning("Fiscal document %s not found", document_id)
        return None

    if document.status == FiscalDocumentStatus.QUEUED:
        document.status = FiscalDocumentStatus.PROCESSING
        db.session.commit()
        logger.info("Fiscal document %s set to PROCESSING", document_id)
    else:
        logger.info(
            "Fiscal document %s status unchanged (current=%s)",
            document_id,
            document.status.value,
        )
    return document


_retry_kwargs = {
    "autoretry_for": (Exception,),
    "retry_backoff": True,
    "retry_backoff_max": 300,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 5},
}


@celery_app.task(name="jobs.emit_nfse", **_retry_kwargs)
def emit_nfse(document_id: int) -> dict:
    document = _mark_processing(document_id)
    logger.info("Emitindo NFSe para documento %s", document_id)
    return {"document_id": document_id, "status": document.status.value if document else None}


@celery_app.task(name="jobs.emit_nfe", **_retry_kwargs)
def emit_nfe(document_id: int) -> dict:
    document = _mark_processing(document_id)
    logger.info("Emitindo NFe para documento %s", document_id)
    return {"document_id": document_id, "status": document.status.value if document else None}


@celery_app.task(name="jobs.poll_nfse", **_retry_kwargs)
def poll_nfse(document_id: int) -> dict:
    document = _mark_processing(document_id)
    logger.info("Consultando NFSe para documento %s", document_id)
    return {"document_id": document_id, "status": document.status.value if document else None}


@celery_app.task(name="jobs.poll_nfe", **_retry_kwargs)
def poll_nfe(document_id: int) -> dict:
    document = _mark_processing(document_id)
    logger.info("Consultando NFe para documento %s", document_id)
    return {"document_id": document_id, "status": document.status.value if document else None}
