"""Animal search utilities for /buscar_animais endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional

from sqlalchemy import func, or_, true
from sqlalchemy.orm import contains_eager, joinedload

from extensions import db
from models import Animal
from models.agenda import Appointment

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
    from models.base import Breed, Species

    like_term = f"%{(term or '').strip()}%"
    sort_value = _coerce_sort(sort)
    max_results = min(limit or DEFAULT_LIMIT, DEFAULT_LIMIT)

    # outerjoin Species and Breed so we can filter by their names
    query = (
        Animal.query
        .outerjoin(Animal.species)
        .outerjoin(Animal.breed)
        .options(
            joinedload(Animal.owner),
            contains_eager(Animal.species),
            contains_eager(Animal.breed),
        )
        .filter(Animal.removido_em.is_(None))
    )

    # Apply text filter only when a term is provided
    if (term or '').strip():
        filters = [
            Animal.name.ilike(like_term),
            Animal.microchip_number.ilike(like_term),
            Species.name.ilike(like_term),
            Breed.name.ilike(like_term),
        ]
        query = query.filter(or_(*filters))

    if visibility_clause is not None:
        query = query.filter(Animal.owner.has(visibility_clause))

    if not is_admin and clinic_scope:
        query = query.filter(Animal.clinica_id == clinic_scope)

    if tutor_id:
        query = query.filter(Animal.user_id == tutor_id)

    if sort_value == "recent_attended":
        last_appt = _build_last_appointment_subquery(clinic_scope)
        query = (
            query
            .outerjoin(last_appt, Animal.id == last_appt.c.animal_id)
            .add_columns(last_appt.c.last_at.label("last_appointment_at"))
            .order_by(func.coalesce(last_appt.c.last_at, Animal.date_added).desc())
        )
        results_raw: Iterable[tuple[Animal, Optional[datetime]]] = query.limit(max_results).all()
        results = results_raw
    else:
        # Optimization (Bolt): For non-`recent_attended` sorts, defer the appointment aggregation query.
        # Joining `_build_last_appointment_subquery` upfront causes full-table GROUP BY over all appointments
        # in the DB on every search query. Filtering and limiting animals first (max 50) and querying
        # max scheduled_at only for matching animal IDs avoids full-table aggregations.
        if sort_value == "name_asc":
            query = query.order_by(Animal.name.asc())
        else:
            query = query.order_by(Animal.date_added.desc())

        animals: List[Animal] = query.limit(max_results).all()
        animal_ids = [a.id for a in animals]
        last_at_map = {}
        if animal_ids:
            last_appt = _build_last_appointment_subquery(clinic_scope)
            appt_query = (
                db.session.query(last_appt.c.animal_id, last_appt.c.last_at)
                .filter(last_appt.c.animal_id.in_(animal_ids))
            )
            last_at_map = dict(appt_query.all())

        results = [(animal, last_at_map.get(animal.id)) for animal in animals]

    serialized: List[dict] = []
    for animal, last_at in results:
        owner = getattr(animal, "owner", None)
        date_of_birth = animal.date_of_birth.strftime("%Y-%m-%d") if animal.date_of_birth else ""
        last_at_value = last_at.isoformat() if isinstance(last_at, datetime) else None

        species_obj = getattr(animal, "species", None)
        species_name = getattr(species_obj, "name", None)

        breed_obj = getattr(animal, "breed", None)
        breed_name = getattr(breed_obj, "name", None)

        serialized.append(
            {
                "id": animal.id,
                "name": animal.name,
                "species": species_name,
                "breed": breed_name,
                "sex": animal.sex,
                "date_of_birth": date_of_birth,
                "microchip_number": animal.microchip_number,
                "peso": animal.peso,
                "health_plan": animal.health_plan,
                "neutered": int(animal.neutered) if animal.neutered is not None else "",
                "tutor_id": getattr(owner, "id", None),
                "tutor_name": getattr(owner, "name", None),
                "species_name": species_name,
                "breed_name": breed_name,
                "age_display": animal.age_display,
                "last_appointment_at": last_at_value,
                "clinic_id": animal.clinica_id,
            }
        )

    return serialized
