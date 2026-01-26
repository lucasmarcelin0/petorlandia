from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from flask import current_app

from extensions import db
from models import Consulta, NfseEvent, NfseIssue
from services.nfse_service import NfseService, _normalize_municipio
from time_utils import utcnow


@dataclass
class NfseQueueResult:
    processed: int
    failed: int
    errors: list[str]


@dataclass
class NfseCancelRules:
    deadline_days: Optional[int]
    require_reason: bool
    allowed_reasons: list[dict[str, str]]


def ensure_nfse_issue_for_consulta(consulta: Consulta) -> Optional[NfseIssue]:
    if not consulta.clinica or not consulta.clinica.municipio_nfse:
        return None

    internal_identifier = f"consulta:{consulta.id}"
    existing = NfseIssue.query.filter_by(
        clinica_id=consulta.clinica_id,
        internal_identifier=internal_identifier,
    ).first()
    if existing:
        return existing

    valor_total = sum((item.valor for item in consulta.orcamento_items), start=0) if consulta.orcamento_items else 0
    issue = NfseIssue(
        clinica_id=consulta.clinica_id,
        internal_identifier=internal_identifier,
        rps=f"CONS-{consulta.id}",
        serie="A1",
        status="fila",
        data_emissao=consulta.finalizada_em or utcnow(),
        valor_total=valor_total or None,
        tomador=json.dumps(
            {
                "tutor_id": consulta.animal.user_id,
                "tutor_nome": consulta.animal.owner.name if consulta.animal.owner else None,
                "animal_id": consulta.animal_id,
                "animal_nome": consulta.animal.name if consulta.animal else None,
            },
            ensure_ascii=False,
        ),
        prestador=json.dumps(
            {
                "clinica_id": consulta.clinica_id,
                "clinica_nome": consulta.clinica.nome if consulta.clinica else None,
                "cnpj": consulta.clinica.cnpj if consulta.clinica else None,
            },
            ensure_ascii=False,
        ),
    )
    db.session.add(issue)
    db.session.flush()
    _register_nfse_event(
        issue=issue,
        event_type="fila_criada",
        status="fila",
        descricao="Emissão criada a partir da finalização de consulta.",
        payload={"consulta_id": consulta.id},
    )
    return issue


def queue_nfse_issue(issue: NfseIssue, reason: str, payload: Optional[dict[str, Any]] = None) -> None:
    issue.status = "fila"
    issue.updated_at = utcnow()
    db.session.add(issue)
    _register_nfse_event(
        issue=issue,
        event_type="enfileirado",
        status="fila",
        descricao=reason,
        payload=payload,
    )
    db.session.commit()


def process_nfse_issue(issue: NfseIssue, payload: Optional[dict[str, Any]] = None) -> None:
    if not issue.clinica or not issue.clinica.municipio_nfse:
        raise ValueError("Clínica sem município NFS-e configurado.")

    issue.status = "processando"
    issue.updated_at = utcnow()
    db.session.add(issue)
    _register_nfse_event(
        issue=issue,
        event_type="emissao_iniciada",
        status="processando",
        descricao="Emissão enviada para o provedor NFS-e.",
        payload=payload,
    )
    db.session.commit()

    service = NfseService()
    municipio = issue.clinica.municipio_nfse
    result = service.emitir_nfse(issue, payload or {}, municipio)
    _register_nfse_event(
        issue=issue,
        event_type="emissao_concluida",
        status=result.status,
        descricao=result.mensagem or "Resposta recebida do provedor.",
        payload={
            "success": result.success,
            "protocolo": result.protocolo,
            "numero_nfse": result.numero_nfse,
        },
    )
    db.session.commit()


def process_nfse_queue(clinica_id: Optional[int] = None, limit: int = 20) -> NfseQueueResult:
    query = NfseIssue.query.filter(NfseIssue.status == "fila")
    if clinica_id:
        query = query.filter(NfseIssue.clinica_id == clinica_id)
    issues = query.order_by(NfseIssue.created_at.asc()).limit(limit).all()

    processed = 0
    failed = 0
    errors: list[str] = []
    for issue in issues:
        try:
            process_nfse_issue(issue)
            processed += 1
        except Exception as exc:  # noqa: BLE001 - precisamos capturar falhas do provedor
            issue.status = "erro"
            issue.erro_mensagem = str(exc)
            issue.erro_em = utcnow()
            db.session.add(issue)
            _register_nfse_event(
                issue=issue,
                event_type="erro_emissao",
                status="erro",
                descricao=str(exc),
                payload=None,
            )
            db.session.commit()
            failed += 1
            errors.append(f"NFS-e {issue.id}: {exc}")

    return NfseQueueResult(processed=processed, failed=failed, errors=errors)


def should_emit_async(municipio: str) -> bool:
    if not municipio:
        return False
    configured = current_app.config.get("NFSE_ASYNC_MUNICIPIOS", [])
    if not configured:
        return False
    normalized = _normalize_municipio(municipio)
    configured_normalized = {_normalize_municipio(item) for item in configured}
    return normalized in configured_normalized


def get_nfse_cancel_rules(municipio: str) -> NfseCancelRules:
    config = current_app.config.get("NFSE_CANCEL_RULES", {})
    normalized = _normalize_municipio(municipio or "")
    payload = config.get(normalized, {})
    return NfseCancelRules(
        deadline_days=payload.get("deadline_days"),
        require_reason=bool(payload.get("require_reason", False)),
        allowed_reasons=list(payload.get("allowed_reasons") or []),
    )


def validate_nfse_cancel_request(
    issue: NfseIssue,
    rules: NfseCancelRules,
    reason_code: Optional[str],
    reason_description: Optional[str],
    substituicao: bool,
    substituida_por_nfse: Optional[str],
) -> list[str]:
    errors: list[str] = []
    if issue.status in {"cancelada", "cancelamento_solicitado", "substituicao_solicitada"}:
        errors.append("A NFS-e já está em cancelamento/substituição.")
    if not issue.numero_nfse:
        errors.append("A NFS-e ainda não possui número para cancelamento/substituição.")

    reason_code = (reason_code or "").strip()
    reason_description = (reason_description or "").strip()

    if rules.require_reason and not (reason_code or reason_description):
        errors.append("Informe o motivo exigido pelo município.")

    if reason_code and rules.allowed_reasons:
        allowed_codes = {item.get("code") for item in rules.allowed_reasons}
        if reason_code not in allowed_codes:
            errors.append("O motivo informado não é permitido pelo município.")

    if rules.deadline_days:
        base_date = issue.data_emissao or issue.created_at
        if base_date:
            deadline = base_date + timedelta(days=rules.deadline_days)
            if utcnow() > deadline:
                errors.append("Prazo de cancelamento/substituição expirado para este município.")

    if substituicao and not (substituida_por_nfse or "").strip():
        errors.append("Informe o número da NFS-e substituta.")

    return errors


def request_nfse_cancel(
    issue: NfseIssue,
    reason_code: Optional[str],
    reason_description: Optional[str],
    payload: Optional[dict[str, Any]] = None,
) -> None:
    municipio = issue.clinica.municipio_nfse if issue.clinica else ""
    service = NfseService()
    result = service.cancelar_nfse(issue, payload or {}, municipio)
    reason_text = _format_nfse_reason(reason_code, reason_description)
    issue.cancelamento_motivo = reason_text
    issue.cancelamento_protocolo = result.protocolo or issue.cancelamento_protocolo
    issue.updated_at = utcnow()
    db.session.add(issue)
    _register_nfse_event(
        issue=issue,
        event_type="cancelamento_solicitado",
        status=result.status,
        descricao=reason_text or "Cancelamento solicitado.",
        payload={
            "reason_code": reason_code,
            "reason_description": reason_description,
            "protocolo": result.protocolo,
        },
    )
    db.session.commit()


def request_nfse_substitution(
    issue: NfseIssue,
    reason_code: Optional[str],
    reason_description: Optional[str],
    substituida_por_nfse: str,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    reason_text = _format_nfse_reason(reason_code, reason_description)
    issue.status = "substituicao_solicitada"
    issue.cancelamento_motivo = reason_text
    issue.substituida_por_nfse = substituida_por_nfse.strip()
    issue.updated_at = utcnow()
    db.session.add(issue)
    _register_nfse_event(
        issue=issue,
        event_type="substituicao_solicitada",
        status=issue.status,
        descricao=reason_text or "Substituição solicitada.",
        payload={
            "reason_code": reason_code,
            "reason_description": reason_description,
            "substituida_por_nfse": substituida_por_nfse,
            **(payload or {}),
        },
    )
    db.session.commit()


def _format_nfse_reason(reason_code: Optional[str], reason_description: Optional[str]) -> str:
    code = (reason_code or "").strip()
    description = (reason_description or "").strip()
    if code and description:
        return f"{code} - {description}"
    return description or code


def _register_nfse_event(
    issue: NfseIssue,
    event_type: str,
    status: Optional[str],
    descricao: str,
    payload: Optional[dict[str, Any]],
) -> None:
    db.session.add(
        NfseEvent(
            clinica_id=issue.clinica_id,
            nfse_issue_id=issue.id,
            event_type=event_type,
            status=status,
            descricao=descricao,
            payload=json.dumps(payload, ensure_ascii=False) if payload else None,
            data_evento=utcnow(),
        )
    )
