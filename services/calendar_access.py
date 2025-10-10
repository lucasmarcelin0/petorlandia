"""Utilities for computing calendar access permissions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Set, Union

from flask_login import AnonymousUserMixin

try:
    from models import ClinicStaff, Clinica
except ImportError:  # pragma: no cover - fallback for local package layout
    from petorlandia.models import ClinicStaff, Clinica


VetLike = Union[object, dict]


@dataclass(frozen=True)
class CalendarAccessScope:
    """Represents the calendar visibility scope for a given user."""

    clinic_ids: Optional[Set[int]] = field(default=None)
    veterinarian_ids: Optional[Set[int]] = field(default=None)

    def allows_all_clinics(self) -> bool:
        return self.clinic_ids is None

    def allows_all_veterinarians(self) -> bool:
        return self.veterinarian_ids is None

    def _normalize_vet_id(self, vet: VetLike) -> Optional[int]:
        if vet is None:
            return None
        if isinstance(vet, dict):
            for key in ('id', 'vet_id', 'veterinario_id', 'veterinarioId'):
                value = vet.get(key)
                if value is not None:
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None
            return None
        candidate = getattr(vet, 'id', None)
        if candidate is None:
            return None
        try:
            return int(candidate)
        except (TypeError, ValueError):
            return None

    def allows_veterinarian(self, vet: VetLike) -> bool:
        vet_id = self._normalize_vet_id(vet)
        if vet_id is None or self.veterinarian_ids is None:
            return True
        return vet_id in self.veterinarian_ids

    def allows_clinic(self, clinic_id: Optional[int]) -> bool:
        if clinic_id is None or self.clinic_ids is None:
            return True
        return clinic_id in self.clinic_ids

    def filter_veterinarians(self, vets: Sequence[VetLike]) -> List[VetLike]:
        return [vet for vet in vets if self.allows_veterinarian(vet)]

    def filter_clinic_ids(self, clinic_ids: Iterable[Optional[int]]) -> List[int]:
        seen: Set[int] = set()
        result: List[int] = []
        for clinic_id in clinic_ids:
            if clinic_id is None:
                continue
            try:
                normalized = int(clinic_id)
            except (TypeError, ValueError):
                continue
            if not self.allows_clinic(normalized):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result


def _user_is_authenticated(user: object) -> bool:
    if user is None:
        return False
    if isinstance(user, AnonymousUserMixin):  # pragma: no cover - safety
        return False
    return bool(getattr(user, 'is_authenticated', False))


def get_calendar_access_scope(user: object) -> CalendarAccessScope:
    """Return the calendar access scope for ``user``.

    Admins and clinic owners can see the full calendar (no filtering). Staff
    members with ``can_view_full_calendar`` disabled are limited to their own
    veterinarian schedule, if available.
    """

    if not _user_is_authenticated(user):
        return CalendarAccessScope()

    if getattr(user, 'role', None) == 'admin':
        return CalendarAccessScope()

    user_id = getattr(user, 'id', None)
    if not user_id:
        return CalendarAccessScope()

    staff_memberships = ClinicStaff.query.filter_by(user_id=user_id).all()
    if not staff_memberships:
        return CalendarAccessScope()

    owned_clinic_ids = {
        clinic.id for clinic in Clinica.query.filter_by(owner_id=user_id).all()
    }

    memberships_by_clinic: dict[int, list[ClinicStaff]] = {}
    for membership in staff_memberships:
        clinic_id = getattr(membership, "clinic_id", None)
        if clinic_id is None:
            continue
        memberships_by_clinic.setdefault(int(clinic_id), []).append(membership)

    restricted_memberships = []
    for clinic_id, memberships in memberships_by_clinic.items():
        if clinic_id in owned_clinic_ids:
            continue
        # If any membership grants full calendar access for the clinic we treat
        # the clinic as unrestricted, even if stale duplicate rows still exist
        # with the flag disabled.
        if any(getattr(m, "can_view_full_calendar", False) for m in memberships):
            continue
        restricted_memberships.extend(memberships)

    if not restricted_memberships:
        return CalendarAccessScope()

    veterinarian = getattr(user, 'veterinario', None)
    vet_id = getattr(veterinarian, 'id', None)
    if not vet_id:
        # Without an associated veterinarian we cannot scope more precisely, so
        # fall back to unrestricted access.
        return CalendarAccessScope()

    clinic_scope: Set[int] = {
        membership.clinic_id
        for membership in staff_memberships
        if membership.clinic_id is not None
    }
    if veterinarian and getattr(veterinarian, 'clinica_id', None):
        clinic_scope.add(veterinarian.clinica_id)
    for clinic in getattr(veterinarian, 'clinicas', []) or []:
        clinic_id = getattr(clinic, 'id', None)
        if clinic_id:
            clinic_scope.add(clinic_id)

    # Ensure the restricted clinics are included in the scope to avoid
    # accidentally filtering everything out.
    for membership in restricted_memberships:
        if membership.clinic_id:
            clinic_scope.add(membership.clinic_id)

    veterinarian_scope: Optional[Set[int]]
    if owned_clinic_ids:
        veterinarian_scope = None
    else:
        veterinarian_scope = {vet_id}

    return CalendarAccessScope(
        clinic_ids=clinic_scope or None,
        veterinarian_ids=veterinarian_scope,
    )
