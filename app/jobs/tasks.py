"""Celery task definitions."""
from __future__ import annotations

import logging

from app.jobs.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="jobs.dummy_task")
def dummy_task(message: str = "dummy") -> dict:
    logger.info("Dummy task executed with message=%s", message)
    return {"message": message}
