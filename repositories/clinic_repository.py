"""Clinic data access helpers."""

from __future__ import annotations

from extensions import db
from models import Clinica


class ClinicRepository:
    """Encapsulate clinic queries."""

    def __init__(self, session=None) -> None:
        self._session = session or db.session

    def list_all_ordered(self):
        return Clinica.query.order_by(Clinica.nome.asc()).all()

    def list_by_owner(self, owner_id: int):
        return Clinica.query.filter_by(owner_id=owner_id).all()

    def first_by_owner(self, owner_id: int):
        return Clinica.query.filter_by(owner_id=owner_id).first()

    def list_by_ids(self, clinic_ids):
        ids = [clinic_id for clinic_id in clinic_ids if clinic_id]
        if not ids:
            return []
        return (
            Clinica.query.filter(Clinica.id.in_(ids))
            .order_by(Clinica.nome.asc())
            .all()
        )

    def count_all(self) -> int:
        return Clinica.query.count()

    def list_owned_ids(self, owner_id: int) -> set[int]:
        return {clinic.id for clinic in self.list_by_owner(owner_id) if clinic.id}
