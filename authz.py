from __future__ import annotations

from dataclasses import dataclass
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from flask_login import current_user
from flask import has_request_context, request

from security.redact import redact_sensitive_text


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


AUTHZ_AUDIT_LOGGER = logging.getLogger("authz.audit")
_DENY_EVENTS_WINDOW = deque(maxlen=3000)


def _masked_resource_identifier(resource_identifier: Any) -> str | None:
    if resource_identifier is None:
        return None
    return redact_sensitive_text(str(resource_identifier))


def _audit_authz_decision(
    *,
    user: Any,
    role: str,
    resource: str,
    resource_identifier: Any,
    allowed: bool,
    reason: str,
) -> None:
    ip = None
    user_agent = None
    route = None
    if has_request_context():
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        user_agent = request.headers.get("User-Agent")
        route = request.path

    payload = {
        "event": "authorization_decision",
        "user_id": getattr(user, "id", None),
        "role": role,
        "resource": resource,
        "resource_identifier": _masked_resource_identifier(resource_identifier),
        "result": "allow" if allowed else "deny",
        "reason": reason,
        "ip": _masked_resource_identifier(ip),
        "user_agent": _masked_resource_identifier(user_agent),
        "route": route,
    }
    AUTHZ_AUDIT_LOGGER.info("authz_decision", extra={"authz": payload})

    if not allowed:
        _DENY_EVENTS_WINDOW.append(
            {
                "at": datetime.now(timezone.utc),
                "route": route or "<unknown>",
                "user_id": getattr(user, "id", None),
                "ip": _masked_resource_identifier(ip) or "<unknown>",
            }
        )


def summarize_authz_denials(window_minutes: int = 5, top_n: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Resumo para painel/alerta de picos de 403 por rota/usuário/IP."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, window_minutes))
    recent = [event for event in _DENY_EVENTS_WINDOW if event["at"] >= cutoff]
    by_route = Counter(event["route"] for event in recent)
    by_user = Counter(str(event["user_id"]) for event in recent)
    by_ip = Counter(event["ip"] for event in recent)

    def _top(counter: Counter) -> list[dict[str, Any]]:
        return [{"key": key, "count": count} for key, count in counter.most_common(top_n)]

    return {
        "window_minutes": window_minutes,
        "total_denies": len(recent),
        "by_route": _top(by_route),
        "by_user": _top(by_user),
        "by_ip": _top(by_ip),
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
    # user.clinica_id também marca clientes (tutores) da clínica; só conta
    # como vínculo OPERACIONAL para a equipe. Sem esta condição, qualquer
    # cliente passaria em can_view_clinic/can_manage_* da própria clínica.
    clinic_id = getattr(user, "clinica_id", None)
    worker = (getattr(user, "worker", None) or "").lower()
    if clinic_id and worker in {"colaborador", "staff", "assistente"}:
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
    allowed_roles: list[str] = []
    for role in roles:
        if ROLE_PERMISSION_MATRIX.get(role, {}).get(resource, {}).get(action):
            allowed_roles.append(role)

    reason = (
        f"policy_allows:{','.join(sorted(allowed_roles))}:{resource}:{action}"
        if allowed_roles
        else f"policy_denies_all_roles:{resource}:{action}"
    )
    _audit_authz_decision(
        user=user,
        role=",".join(sorted(roles)) or "anonymous",
        resource=f"{resource}:{action}",
        resource_identifier=None,
        allowed=bool(allowed_roles),
        reason=reason,
    )
    return bool(allowed_roles)


def _is_global_admin(user: Any) -> bool:
    """Admins têm escopo global: operam sobre qualquer clínica.

    A matriz RBAC já concede view/manage total ao admin; o requisito extra de
    pertencer operacionalmente à clínica existe para restringir donos, equipe e
    veterinários, e não deve re-limitar o admin (que não é vinculado a nenhuma
    clínica específica) a um escopo vazio.
    """
    return "admin" in _user_roles(user)


def can_view_clinic(user: Any, clinic_id: int | None) -> bool:
    if not clinic_id or not _can(user, "clinic", "view"):
        return False
    return _is_global_admin(user) or int(clinic_id) in _viewer_operational_clinic_ids(user)


def can_manage_clinic(user: Any, clinic_id: int | None) -> bool:
    if not clinic_id or not _can(user, "clinic", "manage"):
        return False
    return _is_global_admin(user) or int(clinic_id) in _viewer_operational_clinic_ids(user)


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
