"""Explainable business metrics computed from a clinic's own records."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from models import Animal, Appointment, Consulta, Orcamento, Vacina
from time_utils import normalize_to_utc, utcnow


ALLOWED_PERIODS = (30, 90, 365)
OPEN_STATUSES = ("scheduled", "accepted", "in_progress")


def _money(records) -> Decimal:
    return sum((Decimal(str(record.total or 0)) for record in records), Decimal("0"))


def _trend(current: int | float, previous: int | float) -> dict:
    if previous:
        change = ((float(current) - float(previous)) / float(previous)) * 100
        return {"value": round(change, 1), "comparable": True}
    return {"value": None, "comparable": False}


def _utc(value):
    return normalize_to_utc(value) if value is not None else None


def build_clinic_value_report(clinic_id: int, period_days: int = 30) -> dict:
    """Build a clinic report without implying revenue attribution."""

    if period_days not in ALLOWED_PERIODS:
        period_days = 30
    end = utcnow()
    start = end - timedelta(days=period_days)
    previous_start = start - timedelta(days=period_days)

    appointments = (
        Appointment.query.filter(
            Appointment.clinica_id == clinic_id,
            Appointment.scheduled_at >= previous_start,
            Appointment.scheduled_at < end,
        ).all()
    )
    current = [a for a in appointments if _utc(a.scheduled_at) >= start]
    previous = [a for a in appointments if _utc(a.scheduled_at) < start]

    def appointment_stats(items):
        completed = [a for a in items if a.status == "completed"]
        no_shows = [a for a in items if a.status == "no_show"]
        canceled = [a for a in items if a.status == "canceled"]
        decided = len(completed) + len(no_shows) + len(canceled)
        return {
            "total": len(items),
            "completed": len(completed),
            "unique_tutors": len({a.tutor_id for a in items if a.tutor_id}),
            "no_show_rate": round((len(no_shows) / decided) * 100, 1) if decided else 0,
            "cancellation_rate": round((len(canceled) / decided) * 100, 1) if decided else 0,
        }

    current_stats = appointment_stats(current)
    previous_stats = appointment_stats(previous)

    current_completed = [a for a in current if a.status == "completed" and a.animal_id]
    current_animal_ids = {a.animal_id for a in current_completed}
    prior_ids = set()
    if current_animal_ids:
        prior_ids.update(
            row[0] for row in Appointment.query.with_entities(Appointment.animal_id).filter(
                Appointment.clinica_id == clinic_id,
                Appointment.status == "completed",
                Appointment.scheduled_at < start,
                Appointment.animal_id.in_(current_animal_ids),
            ).distinct().all()
        )
        prior_ids.update(
            row[0] for row in Consulta.query.with_entities(Consulta.animal_id).filter(
                Consulta.clinica_id == clinic_id,
                Consulta.status == "finalizada",
                Consulta.created_at < start,
                Consulta.animal_id.in_(current_animal_ids),
            ).distinct().all()
        )

    budgets = Orcamento.query.filter_by(clinica_id=clinic_id).all()
    period_budgets = [
        b for b in budgets
        if b.created_at and start <= _utc(b.created_at) < end
    ]
    approved = [b for b in period_budgets if b.status == "approved"]
    paid = [
        b for b in budgets
        if b.payment_status == "paid"
        and (b.paid_at or b.created_at)
        and start <= _utc(b.paid_at or b.created_at) < end
    ]
    pending = [
        b for b in period_budgets
        if b.status in ("sent", "approved") and b.payment_status != "paid"
    ]

    animal_ids = [row[0] for row in Animal.query.with_entities(Animal.id).filter(
        Animal.clinica_id == clinic_id,
        Animal.removido_em.is_(None),
    ).all()]
    overdue_vaccines = 0
    if animal_ids:
        overdue_vaccines = Vacina.query.filter(
            Vacina.animal_id.in_(animal_ids),
            Vacina.aplicada.is_(False),
            Vacina.aplicada_em.isnot(None),
            Vacina.aplicada_em < end.date(),
        ).count()

    # Patients who have not returned in 180 days and have no future booking.
    retention = []
    if animal_ids:
        future_ids = {
            row[0] for row in Appointment.query.with_entities(Appointment.animal_id).filter(
                Appointment.clinica_id == clinic_id,
                Appointment.animal_id.in_(animal_ids),
                Appointment.scheduled_at >= end,
                Appointment.status.in_(OPEN_STATUSES),
            ).distinct().all()
        }
        last_visits = {}
        for consultation in Consulta.query.filter(
            Consulta.clinica_id == clinic_id,
            Consulta.animal_id.in_(animal_ids),
            Consulta.status == "finalizada",
        ).all():
            value = consultation.finalizada_em or consultation.created_at
            value = _utc(value)
            if value and (consultation.animal_id not in last_visits or value > last_visits[consultation.animal_id]):
                last_visits[consultation.animal_id] = value
        cutoff = end - timedelta(days=180)
        candidates = [animal_id for animal_id, seen in last_visits.items() if seen < cutoff and animal_id not in future_ids]
        if candidates:
            animals = Animal.query.filter(Animal.id.in_(candidates)).all()
            retention = sorted(
                ({"animal": animal, "last_visit": last_visits[animal.id]} for animal in animals),
                key=lambda item: item["last_visit"],
            )[:10]

    return {
        "period_days": period_days,
        "start": start,
        "end": end,
        "appointments": current_stats,
        "returning_patients": len(prior_ids),
        "returning_rate": round((len(prior_ids) / len(current_animal_ids)) * 100, 1) if current_animal_ids else 0,
        "budget_count": len(period_budgets),
        "budget_approved_count": len(approved),
        "budget_approval_rate": round((len(approved) / len(period_budgets)) * 100, 1) if period_budgets else 0,
        "paid_value": _money(paid),
        "pending_value": _money(pending),
        "messages_sent": sum((b.email_sent_count or 0) + (b.whatsapp_sent_count or 0) for b in period_budgets),
        "overdue_vaccines": overdue_vaccines,
        "retention": retention,
        "trends": {
            "appointments": _trend(current_stats["total"], previous_stats["total"]),
            "completed": _trend(current_stats["completed"], previous_stats["completed"]),
            "unique_tutors": _trend(current_stats["unique_tutors"], previous_stats["unique_tutors"]),
        },
    }
