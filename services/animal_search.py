"""Animal search utilities for /buscar_animais endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional

from time import perf_counter

from flask import current_app, has_app_context
from sqlalchemy import func, or_, true
from sqlalchemy.orm import contains_eager, load_only

from extensions import db
from models import Animal, Appointment, User

DEFAULT_LIMIT = 50
VALID_SORTS = {"name_asc", "recent_added", "recent_attended"}


def _build_last_appointment_subquery(clinic_scope: Optional[int]):
    """Return a subquery selecting the last appointment per animal."""
    query = (
        db.session.query(
            Appointment.animal_id,
            func.max(Appointment.scheduled_at).label("last_at"),
        )
        .group_by(Appointment.animal_id)
    )

    if clinic_scope:
        query = query.filter(Appointment.clinica_id == clinic_scope)

    return query.subquery()


def _coerce_sort(value: Optional[str]) -> str:
    if not value:
        return "recent_added"
    if value in VALID_SORTS:
        return value
    return "recent_added"


def search_animals(
    *,
    term: str,
    clinic_scope: Optional[int],
    is_admin: bool,
    visibility_clause,
    sort: Optional[str] = None,
    tutor_id: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[dict]:
    """Return serialized animals for the search endpoint."""

    like_term = f"%{(term or '').strip()}%"

    filters = [Animal.name.ilike(like_term)]

    species_column = getattr(Animal.__table__.c, "species", None)
    if species_column is not None:
        filters.append(species_column.ilike(like_term))

    breed_column = getattr(Animal.__table__.c, "breed", None)
    if breed_column is not None:
        filters.append(breed_column.ilike(like_term))

    filters.append(Animal.microchip_number.ilike(like_term))

    clause = or_(*filters) if filters else true()

    last_appt = _build_last_appointment_subquery(clinic_scope)

    query = (
        db.session.query(Animal)
        .options(
            load_only(
                Animal.id,
                Animal.name,
                Animal.image,
                Animal.date_added,
                Animal.date_of_birth,
                Animal.age,
                Animal.user_id,
            ),
            contains_eager(Animal.owner).load_only(User.id, User.name),
        )
        .outerjoin(User, Animal.owner)
        .outerjoin(last_appt, Animal.id == last_appt.c.animal_id)
        .add_columns(last_appt.c.last_at.label("last_appointment_at"))
        .filter(clause)
        .filter(Animal.removido_em.is_(None))
    )

    if visibility_clause is not None:
        query = query.filter(Animal.owner.has(visibility_clause))

    if not is_admin and clinic_scope:
        query = query.filter(Animal.clinica_id == clinic_scope)

    if tutor_id:
        query = query.filter(Animal.user_id == tutor_id)

    sort_value = _coerce_sort(sort)

    if sort_value == "name_asc":
        query = query.order_by(Animal.name.asc())
    elif sort_value == "recent_attended":
        query = query.order_by(func.coalesce(last_appt.c.last_at, Animal.date_added).desc())
    else:
        query = query.order_by(Animal.date_added.desc())

    max_results = min(limit or DEFAULT_LIMIT, DEFAULT_LIMIT)
    start_time = perf_counter()
    results: Iterable[tuple[Animal, Optional[datetime]]] = query.limit(max_results).all()
    duration_ms = (perf_counter() - start_time) * 1000
    if has_app_context():
        current_app.logger.debug("search_animals fetched %d rows in %.2f ms", len(results), duration_ms)

    serialized: List[dict] = []
    for animal, _ in results:
        owner = getattr(animal, "owner", None)
        date_of_birth = animal.date_of_birth.strftime("%Y-%m-%d") if animal.date_of_birth else ""
        date_added = (
            animal.date_added.isoformat() if getattr(animal, "date_added", None) else ""
        )

        serialized.append(
            {
                "id": animal.id,
                "name": animal.name,
                "image": getattr(animal, "image", None),
                "date_of_birth": date_of_birth,
                "age_display": animal.age_display,
                "date_added": date_added,
                "tutor": {
                    "id": getattr(owner, "id", None),
                    "name": getattr(owner, "name", None),
                },
            }
        )

    return serialized
