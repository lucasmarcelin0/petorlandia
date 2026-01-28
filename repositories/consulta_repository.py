"""Consulta data access helpers."""

from __future__ import annotations

from sqlalchemy.orm import selectinload

from extensions import db
from models import Consulta


class ConsultaRepository:
    """Encapsulate consulta queries."""

    def __init__(self, session=None) -> None:
        self._session = session or db.session

    def history_query(self, *, animal_id: int, clinic_id: int):
        return (
            Consulta.query.options(
                selectinload(Consulta.veterinario),
                selectinload(Consulta.clinica),
            )
            .filter_by(
                animal_id=animal_id,
                status="finalizada",
                clinica_id=clinic_id,
            )
        )

    def paginate_history(
        self,
        *,
        animal_id: int,
        clinic_id: int,
        page: int,
        per_page: int,
    ):
        return (
            self.history_query(animal_id=animal_id, clinic_id=clinic_id)
            .order_by(Consulta.created_at.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
