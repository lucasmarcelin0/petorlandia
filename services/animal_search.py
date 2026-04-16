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

    last_appt = _build_last_appointment_subquery(clinic_scope)

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
        .outerjoin(last_appt, Animal.id == last_appt.c.animal_id)
        .add_columns(last_appt.c.last_at.label("last_appointment_at"))
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

    sort_value = _coerce_sort(sort)

    if sort_value == "name_asc":
        query = query.order_by(Animal.name.asc())
    elif sort_value == "recent_attended":
        query = query.order_by(func.coalesce(last_appt.c.last_at, Animal.date_added).desc())
    else:
        query = query.order_by(Animal.date_added.desc())

    max_results = min(limit or DEFAULT_LIMIT, DEFAULT_LIMIT)
    results: Iterable[tuple[Animal, Optional[datetime]]] = query.limit(max_results).all()

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
