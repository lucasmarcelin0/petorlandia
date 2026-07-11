"""Controle de acesso a usuários, animais e consultas (privacy-aware).

Extraído de app.py na modularização (2026-07-10). Regras:
- get_*_or_404 devolvem 404 (nunca 403) para não vazar existência de recursos
  de outra clínica.
- Compartilhamentos ativos (DataShareAccess) liberam leitura e são auditados
  via _log_data_share.

``ensure_clinic_access`` é resolvido em runtime via módulo app nas chamadas
internas porque testes fazem monkeypatch de ``app.ensure_clinic_access``.
"""
from __future__ import annotations

from flask import abort, request
from flask_login import current_user
from sqlalchemy import and_, false, or_, true

from authz import can_view_clinic
from extensions import db
from helpers import _user_is_clinic_owner, has_professional_access, is_veterinarian
from models import (
    Animal,
    Consulta,
    DataShareAccess,
    DataShareLog,
    DataSharePartyType,
    User,
)
from services.data_share import find_active_share, log_data_share_event
from time_utils import utcnow


def _ensure_clinic_access_latebound(clinica_id):
    import app as app_module

    return app_module.ensure_clinic_access(clinica_id)


def _shared_user_clause(viewer=None, clinic_scope=None):
    parties = _viewer_parties(viewer=viewer, clinic_scope=clinic_scope)
    if not parties:
        return None

    now = utcnow()
    query = (
        db.session.query(DataShareAccess.user_id)
        .filter(DataShareAccess.user_id.isnot(None))
        .filter(DataShareAccess.revoked_at.is_(None))
        .filter(or_(DataShareAccess.expires_at.is_(None), DataShareAccess.expires_at > now))
    )
    party_clauses = [
        and_(
            DataShareAccess.granted_to_type == party_type,
            DataShareAccess.granted_to_id == party_id,
        )
        for party_type, party_id in parties
    ]
    if not party_clauses:
        return None
    query = query.filter(or_(*party_clauses))
    return User.id.in_(query.subquery())


def _collect_clinic_ids(viewer=None, clinic_scope=None):
    """Return a set with clinic IDs derived from the viewer and scope hints."""
    clinic_ids = set()

    if clinic_scope:
        if isinstance(clinic_scope, (list, tuple, set)):
            clinic_ids.update(cid for cid in clinic_scope if cid)
        else:
            if clinic_scope:
                clinic_ids.add(clinic_scope)

    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    if viewer:
        viewer_clinic = getattr(viewer, 'clinica_id', None)
        if viewer_clinic:
            clinic_ids.add(viewer_clinic)

        vet_profile = getattr(viewer, 'veterinario', None)
        if vet_profile:
            primary = getattr(vet_profile, 'clinica_id', None)
            if primary:
                clinic_ids.add(primary)
            for clinic in getattr(vet_profile, 'clinicas', []) or []:
                clinic_id = getattr(clinic, 'id', None)
                if clinic_id:
                    clinic_ids.add(clinic_id)

    return clinic_ids


def _viewer_parties(viewer=None, clinic_scope=None):
    parties = []

    clinic_ids = _collect_clinic_ids(viewer=viewer, clinic_scope=clinic_scope)
    for clinic_id in clinic_ids:
        if clinic_id:
            parties.append((DataSharePartyType.clinic, clinic_id))

    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    if viewer:
        worker = getattr(viewer, 'worker', None)
        viewer_id = getattr(viewer, 'id', None)
        if viewer_id and is_veterinarian(viewer):
            parties.append((DataSharePartyType.veterinarian, viewer_id))
        elif worker == 'seguradora' and viewer_id:
            parties.append((DataSharePartyType.insurer, viewer_id))

    unique = []
    seen = set()
    for party in parties:
        if not party or party[1] is None:
            continue
        key = (party[0].value if isinstance(party[0], DataSharePartyType) else party[0], party[1])
        if key in seen:
            continue
        seen.add(key)
        unique.append(party)
    return unique


def _user_visibility_clause(viewer=None, clinic_scope=None):
    """Return a SQLAlchemy clause enforcing user privacy for listings."""
    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    if viewer and getattr(viewer, 'role', None) == 'admin':
        return true()

    if viewer and has_professional_access(viewer):
        return true()

    clauses = []

    if viewer:
        viewer_id = getattr(viewer, 'id', None)
        if viewer_id:
            clauses.append(User.id == viewer_id)
            clauses.append(User.added_by_id == viewer_id)

    clinic_ids = _collect_clinic_ids(viewer=viewer, clinic_scope=clinic_scope)
    if clinic_ids:
        clauses.append(User.clinica_id.in_(list(clinic_ids)))

    shared_clause = _shared_user_clause(viewer=viewer, clinic_scope=clinic_scope)
    if shared_clause is not None:
        clauses.append(shared_clause)

    if not clauses:
        return false()

    return or_(*clauses)


def _can_view_user(user, viewer=None, clinic_scope=None):
    """Return ``True`` if the viewer can see the given user respecting privacy."""
    if user is None:
        return False

    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    if viewer is None:
        return False

    viewer_id = getattr(viewer, 'id', None)
    if viewer_id and user.id == viewer_id:
        return True

    if viewer_id and user.added_by_id == viewer_id:
        return True

    shared_access = _resolve_shared_access_for_user(user, viewer=viewer, clinic_scope=clinic_scope)
    if getattr(viewer, 'role', None) == 'admin':
        return True

    if shared_access:
        return True

    clinic_ids = _collect_clinic_ids(viewer=viewer, clinic_scope=clinic_scope)
    if has_professional_access(viewer):
        return bool(user.clinica_id and user.clinica_id in clinic_ids)

    return bool(user.clinica_id and user.clinica_id in clinic_ids)


def _resolve_shared_access_for_user(user, viewer=None, clinic_scope=None):
    if not user:
        return None
    parties = _viewer_parties(viewer=viewer, clinic_scope=clinic_scope)
    return find_active_share(parties, user_id=getattr(user, 'id', None))


def _resolve_shared_access_for_animal(animal, viewer=None, clinic_scope=None):
    if not animal:
        return None
    parties = _viewer_parties(viewer=viewer, clinic_scope=clinic_scope)
    user_id = getattr(animal, 'user_id', None)
    animal_id = getattr(animal, 'id', None)
    return find_active_share(parties, user_id=user_id, animal_id=animal_id)


def _resolve_shared_access_for_consulta(consulta, viewer=None, clinic_scope=None):
    if not consulta:
        return None
    if getattr(consulta, 'animal', None):
        return _resolve_shared_access_for_animal(consulta.animal, viewer=viewer, clinic_scope=clinic_scope)
    return None


def _log_data_share(access, *, event_type, resource_type, resource_id=None, actor=None):
    if not access:
        return None
    return log_data_share_event(
        access,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        actor=actor,
    )


def _is_tutor_portal_user(user=None):
    user = user or (current_user if current_user.is_authenticated else None)
    if not user:
        return False
    worker = (getattr(user, 'worker', None) or '').lower()
    return worker not in {'veterinario', 'colaborador', 'admin'}


def get_user_or_404(user_id, *, viewer=None, clinic_scope=None):
    """Load a user enforcing privacy-aware visibility."""
    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    user = User.query.get_or_404(user_id)
    shared_access = _resolve_shared_access_for_user(user, viewer=viewer, clinic_scope=clinic_scope)
    if not shared_access and not _can_view_user(user, viewer=viewer, clinic_scope=clinic_scope):
        abort(404)

    if shared_access:
        _log_data_share(
            shared_access,
            event_type='read',
            resource_type='user',
            resource_id=user.id,
            actor=viewer,
        )
    return user


def ensure_clinic_access(clinica_id):
    """Abort with 404 if the current user cannot view the given clinic."""
    if not clinica_id or not current_user.is_authenticated:
        abort(404)
    if not can_view_clinic(current_user, clinica_id):
        abort(404)


def _viewer_operational_clinic_ids(viewer):
    """Return clinic IDs where the viewer can operate as staff/owner."""

    clinic_ids = []
    if not viewer:
        return clinic_ids

    if _user_is_clinic_owner(viewer):
        for clinic in getattr(viewer, 'clinicas', []) or []:
            clinic_id = getattr(clinic, 'id', None)
            if clinic_id and clinic_id not in clinic_ids:
                clinic_ids.append(clinic_id)

    worker_role = (getattr(viewer, 'worker', None) or '').lower()
    if worker_role == 'colaborador':
        viewer_clinic = getattr(viewer, 'clinica_id', None)
        if viewer_clinic and viewer_clinic not in clinic_ids:
            clinic_ids.append(viewer_clinic)

    vet_profile = getattr(viewer, 'veterinario', None)
    for clinic_id in _veterinarian_accessible_clinic_ids(vet_profile):
        if clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    for role in getattr(viewer, 'clinic_roles', []) or []:
        clinic_id = getattr(role, 'clinic_id', None)
        if clinic_id and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    return clinic_ids


def get_animal_or_404(animal_id, *, viewer=None, clinic_scope=None):
    """Return animal if accessible to current user, otherwise 404."""
    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    animal = Animal.query.get_or_404(animal_id)
    admin_access = bool(viewer and getattr(viewer, 'role', None) == 'admin')
    owner_access = bool(viewer and animal.user_id == viewer.id)
    added_by_access = bool(viewer and animal.added_by_id and animal.added_by_id == viewer.id)
    shared_access = _resolve_shared_access_for_animal(animal, viewer=viewer, clinic_scope=clinic_scope)
    if not admin_access and not shared_access and not owner_access and not added_by_access:
        clinic_id = animal.clinica_id
        if not clinic_id:
            # Animal sem clínica herda o vínculo do tutor-cliente — mesma
            # regra de visibilidade aplicada ao próprio tutor.
            clinic_id = getattr(animal.owner, 'clinica_id', None)
        _ensure_clinic_access_latebound(clinic_id)
    elif shared_access:
        _log_data_share(
            shared_access,
            event_type='read',
            resource_type='animal',
            resource_id=animal.id,
            actor=viewer,
        )

    tutor_id = getattr(animal, "user_id", None)
    if tutor_id and animal.clinica_id:
        visibility_clause = _user_visibility_clause(viewer=viewer, clinic_scope=clinic_scope)
        tutor_visible = (
            db.session.query(User.id)
            .filter(User.id == tutor_id)
            .filter(visibility_clause)
            .first()
        )
        if not tutor_visible and not (shared_access or owner_access or added_by_access):
            abort(404)

    return animal


def get_consulta_or_404(consulta_id, *, viewer=None, clinic_scope=None):
    """Return consulta if accessible to current user, otherwise 404."""
    if viewer is None and current_user.is_authenticated:
        viewer = current_user

    consulta = Consulta.query.get_or_404(consulta_id)
    shared_access = _resolve_shared_access_for_consulta(consulta, viewer=viewer, clinic_scope=clinic_scope)
    if not shared_access:
        clinic_id = consulta.clinica_id
        if not clinic_id:
            # Consultas legadas sem clínica: escopa pela clínica do animal
            # (mesmo fallback usado pelas views ao gravar blocos).
            clinic_id = getattr(consulta.animal, 'clinica_id', None)
        if clinic_id:
            _ensure_clinic_access_latebound(clinic_id)
        else:
            # Sem nenhuma clínica resolvível, apenas o criador ou admin acessa.
            viewer_id = getattr(viewer, 'id', None)
            is_admin_viewer = (getattr(viewer, 'role', '') or '').lower() == 'admin'
            if not is_admin_viewer and (viewer_id is None or consulta.created_by != viewer_id):
                abort(404)
    else:
        _log_data_share(
            shared_access,
            event_type='read',
            resource_type='consulta',
            resource_id=consulta.id,
            actor=viewer,
        )
    return consulta


def _veterinarian_accessible_clinic_ids(vet_profile):
    """Return clinic IDs a veterinarian can operate in."""

    if not vet_profile:
        return []

    clinic_ids = []
    primary = getattr(vet_profile, 'clinica_id', None)
    if primary:
        clinic_ids.append(primary)

    for clinic in getattr(vet_profile, 'clinicas', []) or []:
        clinic_id = getattr(clinic, 'id', None)
        if clinic_id and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    # Clinics the vet's user owns (owner_id == user.id) may not appear in the
    # two sets above when the Veterinario record predates the Clinica or when
    # the staff link was never set.
    for clinic in getattr(getattr(vet_profile, 'user', None), 'clinicas', []) or []:
        clinic_id = getattr(clinic, 'id', None)
        if clinic_id and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    return clinic_ids

