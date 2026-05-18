"""Celery task definitions."""
from __future__ import annotations

import logging

from app.jobs.celery_app import celery_app
from extensions import db
from models import StorePaymentAccount
from services.mercadopago_oauth import renew_due_store_accounts

logger = logging.getLogger(__name__)


@celery_app.task(name="jobs.dummy_task")
def dummy_task(message: str = "dummy") -> dict:
    logger.info("Dummy task executed with message=%s", message)
    return {"message": message}


@celery_app.task(name="jobs.mercadopago_oauth_renewal")
def mercadopago_oauth_renewal() -> dict:
    result = renew_due_store_accounts(db, StorePaymentAccount)
    payload = {
        "checked": result.checked,
        "renewed": result.renewed,
        "failed": result.failed,
    }
    logger.info("Mercado Pago OAuth renewal finished: %s", payload)
    return payload
