"""Contextual, non-clinical next steps for a pet's tutor.

The recommendations are deliberately conservative: they point to existing
services and records, never diagnose a condition or recommend medication.
"""

from __future__ import annotations

from datetime import date, timedelta

from flask import url_for

from models import Appointment, Consulta, Product, Vacina
from time_utils import utcnow


def build_pet_opportunities(animal) -> list[dict]:
    """Return at most three explainable next steps for ``animal``."""

    today = date.today()
    now = utcnow()
    opportunities: list[dict] = []

    overdue_count = (
        Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
        .filter(Vacina.aplicada_em.isnot(None), Vacina.aplicada_em < today)
        .count()
    )
    if overdue_count:
        opportunities.append({
            "kind": "vaccine",
            "tone": "warning",
            "icon": "bi-shield-check",
            "title": "Há dose(s) com data para revisar",
            "description": (
                f"{overdue_count} registro(s) aparece(m) com data anterior a hoje. "
                "Confirme a necessidade e o calendário com um médico-veterinário."
            ),
            "cta": "Ver vacinação",
            "url": url_for("servicos_vacinas", animal_id=animal.id),
            "event": "recommendation_vaccine_review",
        })
    else:
        next_dose = (
            Vacina.query.filter_by(animal_id=animal.id, aplicada=False)
            .filter(
                Vacina.aplicada_em.isnot(None),
                Vacina.aplicada_em >= today,
                Vacina.aplicada_em <= today + timedelta(days=45),
            )
            .order_by(Vacina.aplicada_em)
            .first()
        )
        if next_dose:
            opportunities.append({
                "kind": "vaccine",
                "tone": "info",
                "icon": "bi-calendar2-check",
                "title": "Próxima dose se aproxima",
                "description": (
                    f"Há uma dose registrada para {next_dose.aplicada_em.strftime('%d/%m/%Y')}. "
                    "Você pode comparar profissionais e combinar o atendimento."
                ),
                "cta": "Planejar vacinação",
                "url": url_for("servicos_vacinas", animal_id=animal.id),
                "event": "recommendation_vaccine_upcoming",
            })

    future_appointment = (
        Appointment.query.filter_by(animal_id=animal.id)
        .filter(
            Appointment.scheduled_at >= now,
            Appointment.status.in_(("scheduled", "accepted", "in_progress")),
        )
        .first()
    )
    last_consultation = (
        Consulta.query.filter_by(animal_id=animal.id, status="finalizada")
        .order_by(Consulta.finalizada_em.desc(), Consulta.created_at.desc())
        .first()
    )
    last_seen = None
    if last_consultation:
        last_seen = last_consultation.finalizada_em or last_consultation.created_at
    needs_checkup_prompt = not future_appointment and (
        last_seen is None
        or (last_seen.date() if hasattr(last_seen, "date") else last_seen)
        < today - timedelta(days=180)
    )
    if needs_checkup_prompt:
        opportunities.append({
            "kind": "checkup",
            "tone": "primary",
            "icon": "bi-heart-pulse",
            "title": "Sem atendimento futuro registrado",
            "description": (
                "Se fizer sentido para a rotina do pet, compare serviços e combine uma avaliação. "
                "A periodicidade adequada deve ser definida pelo profissional."
            ),
            "cta": "Encontrar atendimento",
            "url": url_for("servicos", animal_id=animal.id),
            "event": "recommendation_checkup",
        })

    # Cross-sell only real, available catalogue items. It is intentionally
    # generic: health data must not be used to infer or advertise medication.
    product = (
        Product.query.filter(
            Product.status == "active",
            Product.is_demo.is_(False),
            Product.stock > 0,
        )
        .order_by(Product.id.desc())
        .first()
    )
    if product and len(opportunities) < 3:
        opportunities.append({
            "kind": "store",
            "tone": "success",
            "icon": "bi-bag-heart",
            "title": "Item disponível na loja",
            "description": (
                f"{product.name} está disponível para compra. Confira vendedor, preço e "
                "se é compra única ou assinatura antes de decidir."
            ),
            "cta": "Ver produto",
            "url": url_for("produto_detail", product_id=product.id),
            "event": "recommendation_store_product",
        })

    return opportunities[:3]
