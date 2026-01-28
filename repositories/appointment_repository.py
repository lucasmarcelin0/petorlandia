"""Appointment data access helpers."""

from __future__ import annotations

from typing import Iterable, Optional

from extensions import db
from models import Appointment


class AppointmentRepository:
    """Encapsulate appointment queries."""

    def __init__(self, session=None) -> None:
        self._session = session or db.session

    def _base_query(self):
        return Appointment.query

    def list_by_clinic(self, clinic_id: int):
        return self._base_query().filter_by(clinica_id=clinic_id).all()

    def filtered_query(
        self,
        *,
        clinic_id: int,
        start_dt_utc=None,
        end_dt_utc=None,
        vet_id: Optional[int] = None,
        status: Optional[str] = None,
        kind: Optional[str] = None,
    ):
        query = self._base_query().filter_by(clinica_id=clinic_id)
        if start_dt_utc:
            query = query.filter(Appointment.scheduled_at >= start_dt_utc)
        if end_dt_utc:
            query = query.filter(Appointment.scheduled_at < end_dt_utc)
        if vet_id:
            query = query.filter(Appointment.veterinario_id == vet_id)
        if status:
            query = query.filter(Appointment.status == status)
        if kind:
            query = query.filter(Appointment.kind == kind)
        return query

    def list_filtered(
        self,
        *,
        clinic_id: int,
        start_dt_utc=None,
        end_dt_utc=None,
        vet_id: Optional[int] = None,
        status: Optional[str] = None,
        kind: Optional[str] = None,
    ):
        return (
            self.filtered_query(
                clinic_id=clinic_id,
                start_dt_utc=start_dt_utc,
                end_dt_utc=end_dt_utc,
                vet_id=vet_id,
                status=status,
                kind=kind,
            )
            .order_by(Appointment.scheduled_at)
            .all()
        )

    def paginate_for_management(
        self,
        *,
        is_admin: bool,
        clinic_id: Optional[int],
        page: int,
        per_page: int,
    ):
        query = self._base_query().order_by(Appointment.scheduled_at)
        if not is_admin and clinic_id:
            query = query.filter_by(clinica_id=clinic_id)
        return query.paginate(page=page, per_page=per_page, error_out=False)

    def get_distinct_statuses(self, clinic_id: int) -> set[str]:
        rows = (
            self._session.query(Appointment.status)
            .filter(Appointment.clinica_id == clinic_id)
            .distinct()
        )
        return {status for (status,) in rows if status}

    def get_distinct_kinds(self, clinic_id: int) -> set[str]:
        rows = (
            self._session.query(Appointment.kind)
            .filter(Appointment.clinica_id == clinic_id)
            .distinct()
        )
        return {kind for (kind,) in rows if kind}

    def list_future_by_clinic_ids(self, clinic_ids: Iterable[int], now):
        if not clinic_ids:
            return []
        return (
            self._base_query()
            .filter(Appointment.clinica_id.in_(list(clinic_ids)))
            .filter(Appointment.scheduled_at >= now)
            .order_by(Appointment.scheduled_at)
            .all()
        )
