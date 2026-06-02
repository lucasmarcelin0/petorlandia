"""Blocking scheduler responsible for periodic maintenance jobs."""

from __future__ import annotations

import os
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from flask import current_app

from app import app
from scripts.sync_pmo_full_status import run_pmo_full_sync
from services.finance import run_transactions_history_backfill


DEFAULT_DAY = 2
DEFAULT_HOUR = 4
DEFAULT_MINUTE = 30
DEFAULT_MONTHS = 6
DEFAULT_PMO_SYNC_MINUTES = 10


def _parse_clinic_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    values = []
    for item in raw.split(','):
        item = item.strip()
        if not item:
            continue
        try:
            values.append(int(item))
        except ValueError:
            current_app.logger.warning("Ignorando clinic_id inválido no agendador: %s", item)
    return values


def _env_int(name: str, default: int, minimum: int, maximum: int | None = None) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    if parsed < minimum:
        return minimum
    if maximum is not None and parsed > maximum:
        return maximum
    return parsed


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


def _run_backfill() -> None:
    with app.app_context():
        months = _env_int('ACCOUNTING_BACKFILL_MONTHS', DEFAULT_MONTHS, 1)
        reference = os.getenv('ACCOUNTING_BACKFILL_REFERENCE')
        clinic_ids = _parse_clinic_ids(os.getenv('ACCOUNTING_BACKFILL_CLINICS'))
        result = run_transactions_history_backfill(
            months=months,
            reference_month=reference,
            clinic_ids=clinic_ids or None,
        )
        current_app.logger.info(
            '[Scheduler] Backfill executado para %s combinações (%s clínicas, %s meses).',
            result.processed,
            len(result.clinics),
            len(result.months),
        )
        if not result.failures:
            return
        for failure in result.failures:
            current_app.logger.error(
                '[Scheduler] Falha na clínica %s mês %s: %s',
                failure.clinic_id,
                f'{failure.month:%Y-%m}',
                failure.error,
            )


def _run_pmo_sync() -> None:
    with app.app_context():
        if not _env_bool("PMO_SYNC_ENABLED", True):
            current_app.logger.info("[Scheduler] Sincronizacao PMO desativada por PMO_SYNC_ENABLED.")
            return
        try:
            result = run_pmo_full_sync(apply=True, skip_sheet_sync=False)
        except Exception:
            current_app.logger.exception("[Scheduler] Falha na sincronizacao PMO.")
            return
        current_app.logger.info("[Scheduler] Sincronizacao PMO concluida: %s", result)


def main() -> None:
    timezone = os.getenv('SCHEDULER_TZ') or os.getenv('ACCOUNTING_BACKFILL_TZ', 'UTC')
    scheduler = BlockingScheduler(timezone=timezone)
    trigger = CronTrigger(
        day=_env_int('ACCOUNTING_BACKFILL_DAY', DEFAULT_DAY, 1, 28),
        hour=_env_int('ACCOUNTING_BACKFILL_HOUR', DEFAULT_HOUR, 0, 23),
        minute=_env_int('ACCOUNTING_BACKFILL_MINUTE', DEFAULT_MINUTE, 0, 59),
    )
    scheduler.add_job(
        _run_backfill,
        trigger,
        id='monthly-accounting-backfill',
        replace_existing=True,
        max_instances=1,
    )
    pmo_interval = _env_int("PMO_SYNC_INTERVAL_MINUTES", DEFAULT_PMO_SYNC_MINUTES, 1, 1440)
    scheduler.add_job(
        _run_pmo_sync,
        IntervalTrigger(minutes=pmo_interval),
        id='pmo-sheet-sync',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    with app.app_context():
        current_app.logger.info(
            'Agendador iniciado. Backfill mensal em %s. PMO a cada %s minuto(s).',
            trigger,
            pmo_interval,
        )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        with app.app_context():
            current_app.logger.info('Encerrando agendador de backfill contábil.')


if __name__ == '__main__':
    main()
