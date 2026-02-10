"""Celery application setup for background jobs."""
from __future__ import annotations

import os

from celery import Celery, Task
from celery.schedules import crontab

from app import app as flask_app


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def _build_beat_schedule() -> dict[str, dict[str, object]]:
    hour = _env_int("FISCAL_MAINTENANCE_HOUR", 3, 0, 23)
    minute = _env_int("FISCAL_MAINTENANCE_MINUTE", 0, 0, 59)
    return {
        "fiscal-maintenance-daily": {
            "task": "jobs.fiscal_maintenance",
            "schedule": crontab(hour=hour, minute=minute),
        },
    }


def _build_broker_url() -> str:
    return os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _build_result_backend(default_backend: str) -> str:
    return os.getenv("CELERY_RESULT_BACKEND", default_backend)


def _make_celery(app) -> Celery:
    broker_url = _build_broker_url()
    celery = Celery(
        app.import_name,
        broker=broker_url,
        backend=_build_result_backend(broker_url),
        include=[
            "app.jobs.fiscal_tasks",
            "app.jobs.fiscal_maintenance",
            "app.jobs.tasks",
        ],
    )
    celery.conf.update(
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_default_queue=os.getenv("CELERY_DEFAULT_QUEUE", "default"),
        task_track_started=True,
        beat_schedule=_build_beat_schedule(),
    )

    class FlaskTask(Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = FlaskTask
    return celery


celery_app = _make_celery(flask_app)
