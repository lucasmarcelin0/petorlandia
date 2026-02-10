"""Appointment-related service helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from flask import current_app

from extensions import db
from forms import AppointmentForm
from helpers import get_appointment_duration, has_conflict_for_slot, is_slot_available
from models import Appointment, HealthSubscription, Message, Veterinario, get_clinica_field
from services.health_plan import evaluate_consulta_coverages
from services.nfse_queue import (
    ensure_nfse_issue_for_consulta,
    process_nfse_issue,
    queue_nfse_issue,
    should_emit_async,
)
from time_utils import BR_TZ, normalize_to_utc, utcnow


@dataclass(frozen=True)
class ReturnAppointmentDTO:
    date: date
    time: time
    veterinarian_id: int
    reason: Optional[str] = None


@dataclass(frozen=True)
class ReturnAppointmentResult:
    success: bool
    message: str
    category: str


@dataclass
class FinalizeConsultaOutcome:
    status: str
    message: str
    category: str
    form: Optional[AppointmentForm] = None


def schedule_return_appointment(
    *,
    consulta,
    actor_id: int,
    actor_vet_id: Optional[int],
    payload: ReturnAppointmentDTO,
) -> ReturnAppointmentResult:
    scheduled_at_local = datetime.combine(payload.date, payload.time)
    vet_id = payload.veterinarian_id
    if not is_slot_available(vet_id, scheduled_at_local, kind="retorno"):
        return ReturnAppointmentResult(
            success=False,
            message="Horário indisponível para o veterinário selecionado.",
            category="danger",
        )

    duration = get_appointment_duration("retorno")
    if has_conflict_for_slot(vet_id, scheduled_at_local, duration):
        return ReturnAppointmentResult(
            success=False,
            message="Horário indisponível para o veterinário selecionado.",
            category="danger",
        )

    scheduled_at = normalize_to_utc(scheduled_at_local)
    same_user = actor_vet_id and actor_vet_id == vet_id
    appt = Appointment(
        consulta_id=consulta.id,
        animal_id=consulta.animal_id,
        tutor_id=consulta.animal.owner.id,
        veterinario_id=vet_id,
        scheduled_at=scheduled_at,
        notes=payload.reason,
        kind="retorno",
        status="accepted" if same_user else "scheduled",
        created_by=actor_id,
        created_at=utcnow(),
    )
    db.session.add(appt)
    db.session.commit()
    return ReturnAppointmentResult(
        success=True,
        message="Retorno agendado com sucesso.",
        category="success",
    )


def finalize_consulta_flow(
    *,
    consulta,
    actor_id: int,
    actor_vet_id: Optional[int],
    clinic_id: Optional[int],
) -> FinalizeConsultaOutcome:
    if consulta.orcamento_items:
        if not consulta.health_subscription_id:
            active_sub = (
                HealthSubscription.query.filter_by(
                    animal_id=consulta.animal_id, active=True
                ).first()
            )
            if active_sub:
                return FinalizeConsultaOutcome(
                    status="blocked",
                    message=(
                        "Associe e valide o plano de saúde antes de finalizar a consulta."
                    ),
                    category="warning",
                )

        result = evaluate_consulta_coverages(consulta)
        consulta.authorization_status = result["status"]
        consulta.authorization_checked_at = utcnow()
        consulta.authorization_notes = (
            "\n".join(result.get("messages", []))
            if result.get("messages")
            else None
        )
        if result["status"] != "approved":
            db.session.commit()
            return FinalizeConsultaOutcome(
                status="blocked",
                message=(
                    "Cobertura não aprovada. Revise o orçamento ou contate a seguradora."
                ),
                category="danger",
            )

    consulta.status = "finalizada"
    consulta.finalizada_em = utcnow()
    appointment = consulta.appointment
    if appointment and appointment.status != "completed":
        appointment.status = "completed"

    resumo = (
        f"Consulta do {consulta.animal.name} finalizada.\n"
        f"Queixa: {consulta.queixa_principal or 'N/A'}\n"
        f"Conduta: {consulta.conduta or 'N/A'}\n"
        f"Prescrição: {consulta.prescricao or 'N/A'}"
    )
    msg = Message(
        sender_id=actor_id,
        receiver_id=consulta.animal.owner.id,
        animal_id=consulta.animal_id,
        content=resumo,
    )
    db.session.add(msg)

    nfse_issue = ensure_nfse_issue_for_consulta(consulta)
    if nfse_issue and nfse_issue.status in {None, "fila", "erro", "reprocessar"}:
        nfse_payload = {
            "consulta_id": consulta.id,
            "animal_id": consulta.animal_id,
            "tutor_id": consulta.animal.user_id,
        }
        try:
            if should_emit_async(get_clinica_field(consulta.clinica, "municipio_nfse", "")):
                queue_nfse_issue(
                    nfse_issue,
                    "Consulta finalizada; emissão aguardando processamento assíncrono.",
                    nfse_payload,
                )
            else:
                process_nfse_issue(nfse_issue, nfse_payload)
        except Exception as exc:  # noqa: BLE001
            queue_nfse_issue(
                nfse_issue,
                "Falha ao emitir automaticamente; reprocessamento necessário.",
                {"erro": str(exc), **nfse_payload},
            )
            current_app.logger.exception(
                "Falha ao emitir NFS-e da consulta %s.",
                consulta.id,
                exc_info=exc,
            )

    if appointment:
        db.session.commit()
        return FinalizeConsultaOutcome(
            status="completed",
            message="Consulta finalizada e retorno já agendado.",
            category="success",
        )

    form = _build_return_form(consulta, clinic_id)
    db.session.commit()
    return FinalizeConsultaOutcome(
        status="needs_return",
        message="Consulta finalizada e registrada no histórico! Agende o retorno.",
        category="success",
        form=form,
    )


def _build_return_form(consulta, clinic_id: Optional[int]) -> AppointmentForm:
    form = AppointmentForm()
    form.populate_animals(
        [consulta.animal],
        restrict_tutors=True,
        selected_tutor_id=getattr(consulta.animal, "user_id", None),
        allow_all_option=False,
    )
    form.animal_id.data = consulta.animal.id

    vets = (
        Veterinario.query.filter_by(clinica_id=clinic_id).all()
        if clinic_id
        else []
    )
    form.veterinario_id.choices = [(v.id, v.user.name) for v in vets]

    vet_id = None
    if consulta.veterinario and getattr(consulta.veterinario, "veterinario", None):
        vet_id = consulta.veterinario.veterinario.id
    if vet_id:
        form.veterinario_id.data = vet_id

    dias_retorno = current_app.config.get("DEFAULT_RETURN_DAYS", 7)
    data_recomendada = (datetime.now(BR_TZ) + timedelta(days=dias_retorno)).date()
    form.date.data = data_recomendada
    form.time.data = time(10, 0)
    return form
