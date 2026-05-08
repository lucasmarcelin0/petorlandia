from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask_login import current_user


SENSITIVE_RESOURCES = {
    "clinic": "Dados gerais e administrativos da clínica",
    "budget": "Orçamentos, itens e blocos de orçamento",
    "consultation": "Consultas, evoluções e prontuário clínico",
    "financial": "Pagamentos, relatórios contábeis e fluxo financeiro",
    "fiscal_documents": "NFSe/NFe, certificados e documentos fiscais",
    "personal_data": "Dados pessoais de tutores, veterinários e equipe",
}

ROLE_PERMISSION_MATRIX = {
    "admin": {resource: {"view": True, "manage": True} for resource in SENSITIVE_RESOURCES},
    "owner": {resource: {"view": True, "manage": True} for resource in SENSITIVE_RESOURCES},
    "staff": {
        "clinic": {"view": True, "manage": False},
        "budget": {"view": True, "manage": True},
        "consultation": {"view": True, "manage": True},
        "financial": {"view": True, "manage": False},
        "fiscal_documents": {"view": False, "manage": False},
        "personal_data": {"view": True, "manage": False},
    },
    "veterinario": {
        "clinic": {"view": True, "manage": False},
        "budget": {"view": True, "manage": True},
        "consultation": {"view": True, "manage": True},
        "financial": {"view": True, "manage": False},
        "fiscal_documents": {"view": False, "manage": False},
        "personal_data": {"view": True, "manage": False},
    },
    "tutor": {
        "clinic": {"view": False, "manage": False},
        "budget": {"view": True, "manage": False},
        "consultation": {"view": True, "manage": False},
        "financial": {"view": False, "manage": False},
        "fiscal_documents": {"view": False, "manage": False},
        "personal_data": {"view": True, "manage": True},
    },
}


def _user_roles(user: Any) -> set[str]:
    if not user:
        return set()
    roles: set[str] = set()
    if getattr(user, "role", None) == "admin":
        roles.add("admin")
    worker = (getattr(user, "worker", None) or "").lower()
    if worker in {"colaborador", "staff", "assistente"}:
        roles.add("staff")
    if worker == "veterinario" or getattr(user, "veterinario", None):
        roles.add("veterinario")
    if getattr(user, "clinicas", None):
        roles.add("owner")
    if not roles:
        roles.add("tutor")
    return roles


def _viewer_operational_clinic_ids(user: Any) -> set[int]:
    ids: set[int] = set()
    if not user:
        return ids
    for clinic in getattr(user, "clinicas", []) or []:
        if getattr(clinic, "id", None):
            ids.add(clinic.id)
    clinic_id = getattr(user, "clinica_id", None)
    if clinic_id:
        ids.add(clinic_id)
    vet = getattr(user, "veterinario", None)
    if vet:
        if getattr(vet, "clinica_id", None):
            ids.add(vet.clinica_id)
        for clinic in getattr(vet, "clinicas", []) or []:
            if getattr(clinic, "id", None):
                ids.add(clinic.id)
    for role in getattr(user, "clinic_roles", []) or []:
        if getattr(role, "clinic_id", None):
            ids.add(role.clinic_id)
    return ids


def _can(user: Any, resource: str, action: str) -> bool:
    roles = _user_roles(user)
    for role in roles:
        if ROLE_PERMISSION_MATRIX.get(role, {}).get(resource, {}).get(action):
            return True
    return False


def can_view_clinic(user: Any, clinic_id: int | None) -> bool:
    return bool(clinic_id) and _can(user, "clinic", "view") and int(clinic_id) in _viewer_operational_clinic_ids(user)


def can_manage_clinic(user: Any, clinic_id: int | None) -> bool:
    return bool(clinic_id) and _can(user, "clinic", "manage") and int(clinic_id) in _viewer_operational_clinic_ids(user)


def can_view_budget(user: Any, clinic_id: int | None, consultation_id: int | None = None) -> bool:
    del consultation_id
    return bool(clinic_id) and _can(user, "budget", "view") and int(clinic_id) in _viewer_operational_clinic_ids(user)


def can_manage_budget(user: Any, clinic_id: int | None, consultation_id: int | None = None) -> bool:
    del consultation_id
    return bool(clinic_id) and _can(user, "budget", "manage") and int(clinic_id) in _viewer_operational_clinic_ids(user)


def can_view_financial(user: Any, clinic_id: int | None) -> bool:
    return bool(clinic_id) and _can(user, "financial", "view") and int(clinic_id) in _viewer_operational_clinic_ids(user)


def can_view_fiscal_documents(user: Any, clinic_id: int | None) -> bool:
    return bool(clinic_id) and _can(user, "fiscal_documents", "view") and int(clinic_id) in _viewer_operational_clinic_ids(user)


def can_manage_fiscal_documents(user: Any, clinic_id: int | None) -> bool:
    return bool(clinic_id) and _can(user, "fiscal_documents", "manage") and int(clinic_id) in _viewer_operational_clinic_ids(user)


def can_view_personal_data(user: Any, owner_user_id: int | None) -> bool:
    return bool(user and owner_user_id and getattr(user, "id", None) == owner_user_id) or _can(user, "personal_data", "view")


def get_clinic_or_403(clinic_id: int | None, user: Any):
    """Carrega clínica somente dentro do escopo autorizado do usuário."""
    if not clinic_id:
        return None
    try:
        clinic_id = int(clinic_id)
    except (TypeError, ValueError):
        return None
    if not can_view_clinic(user, clinic_id):
        return None

    from models import Clinica

    return Clinica.query.filter_by(id=clinic_id).first()
