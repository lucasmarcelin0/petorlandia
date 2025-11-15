"""Helpers for plano de saúde, autorizações e dashboards."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from flask import current_app
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from extensions import db
from models import (
    Consulta,
    HealthCoverage,
    HealthCoverageUsage,
    HealthPlan,
    HealthSubscription,
    OrcamentoItem,
)

COVERAGE_STATUS_LABELS: Dict[str, str] = {
    'approved': 'Aprovado',
    'pending': 'Pendente',
    'denied': 'Negado',
    'waiting_period': 'Em carência',
    'limit_exceeded': 'Limite excedido',
    'no_rule': 'Fora da cobertura',
}

COVERAGE_STATUS_BADGES: Dict[str, str] = {
    'approved': 'success',
    'pending': 'secondary',
    'denied': 'danger',
    'waiting_period': 'warning',
    'limit_exceeded': 'warning',
    'no_rule': 'dark',
}


def coverage_label(value: Optional[str]) -> str:
    return COVERAGE_STATUS_LABELS.get(value or 'pending', 'Pendente')


def coverage_badge(value: Optional[str]) -> str:
    return COVERAGE_STATUS_BADGES.get(value or 'pending', 'secondary')


def _normalize_code(value: Optional[str]) -> str:
    return (value or '').strip().lower()


def _match_coverage(plan: HealthPlan, item: OrcamentoItem) -> Optional[HealthCoverage]:
    if item.coverage:
        return item.coverage
    candidates: Iterable[str] = (
        item.procedure_code,
        getattr(item.servico, 'procedure_code', None) if item.servico else None,
        item.descricao,
    )
    normalized_candidates = {_normalize_code(candidate) for candidate in candidates if candidate}
    for coverage in plan.coverages:
        if _normalize_code(coverage.procedure_code) in normalized_candidates:
            return coverage
    return None


def _usage_amount_for_period(subscription_id: int, coverage_id: int, period: str, reference: datetime) -> Decimal:
    period = (period or 'lifetime').lower()
    query = HealthCoverageUsage.query.filter_by(
        subscription_id=subscription_id,
        coverage_id=coverage_id,
        status='approved',
    )
    if period == 'per_mes':
        start = reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(HealthCoverageUsage.created_at >= start)
    elif period == 'per_ano':
        start = reference.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(HealthCoverageUsage.created_at >= start)
    elif period == 'per_consulta':
        return Decimal('0')
    total = query.with_entities(func.coalesce(func.sum(HealthCoverageUsage.amount_covered), 0)).scalar()
    if total is None:
        return Decimal('0')
    if isinstance(total, Decimal):
        return total
    return Decimal(str(total))


def evaluate_consulta_coverages(consulta: Consulta) -> Dict[str, object]:
    subscription = consulta.health_subscription
    if not subscription or not subscription.plan:
        return {'status': 'no_plan', 'messages': ['Nenhum plano foi selecionado para esta consulta.']}

    plan = subscription.plan
    overall_status = 'approved'
    messages: List[str] = []
    now = datetime.utcnow()

    for item in consulta.orcamento_items:
        coverage = _match_coverage(plan, item)
        if not coverage:
            item.coverage_status = 'no_rule'
            item.coverage_message = 'Procedimento não contemplado pelo plano.'
            overall_status = 'denied'
            continue

        item.coverage_id = coverage.id
        eligible_amount = Decimal(item.valor or 0)
        deductible = Decimal(coverage.deductible_amount or 0)
        if deductible > 0:
            eligible_amount = max(Decimal('0'), eligible_amount - deductible)

        if coverage.waiting_period_days:
            start_date = subscription.start_date or datetime.utcnow()
            eligible_at = start_date + timedelta(days=int(coverage.waiting_period_days))
            if now < eligible_at:
                item.coverage_status = 'waiting_period'
                item.coverage_message = f'Carência ativa até {eligible_at.date().isoformat()}.'
                overall_status = 'denied'
                continue

        if coverage.monetary_limit:
            consumed = _usage_amount_for_period(
                subscription.id,
                coverage.id,
                coverage.limit_period or 'lifetime',
                now,
            )
            remaining = Decimal(coverage.monetary_limit or 0) - consumed
            if eligible_amount > remaining:
                item.coverage_status = 'limit_exceeded'
                item.coverage_message = 'Limite monetário excedido para este procedimento.'
                overall_status = 'denied'
                continue

        item.coverage_status = 'approved'
        item.coverage_message = 'Cobertura autorizada automaticamente.'

        usage = item.usage_record or HealthCoverageUsage(
            subscription_id=subscription.id,
            coverage_id=coverage.id,
            consulta_id=consulta.id,
            orcamento_item_id=item.id,
        )
        usage.amount_billed = eligible_amount
        usage.amount_covered = eligible_amount
        usage.status = 'approved'
        usage.notes = item.coverage_message
        db.session.add(usage)
        messages.append(f"{item.descricao}: {coverage_label('approved')}")

    if overall_status != 'approved' and not messages:
        messages.append('Nenhum item da consulta pôde ser autorizado.')

    return {'status': overall_status, 'messages': messages}


def summarize_plan_metrics() -> List[Dict[str, object]]:
    metrics: List[Dict[str, object]] = []
    plans = HealthPlan.query.order_by(HealthPlan.name).all()
    for plan in plans:
        avg_cost = (
            db.session.query(func.avg(OrcamentoItem.valor))
            .join(Consulta, OrcamentoItem.consulta_id == Consulta.id)
            .filter(Consulta.health_plan_id == plan.id, Consulta.status == 'finalizada')
            .scalar()
        )
        diagnosticos = (
            db.session.query(Consulta.queixa_principal, func.count(Consulta.id))
            .filter(Consulta.health_plan_id == plan.id, Consulta.queixa_principal.isnot(None))
            .group_by(Consulta.queixa_principal)
            .order_by(func.count(Consulta.id).desc())
            .limit(5)
            .all()
        )
        total_usages = (
            db.session.query(func.count(HealthCoverageUsage.id))
            .join(HealthSubscription, HealthCoverageUsage.subscription_id == HealthSubscription.id)
            .filter(HealthSubscription.plan_id == plan.id)
            .scalar()
        ) or 0
        denied_usages = (
            db.session.query(func.count(HealthCoverageUsage.id))
            .join(HealthSubscription, HealthCoverageUsage.subscription_id == HealthSubscription.id)
            .filter(
                HealthSubscription.plan_id == plan.id,
                HealthCoverageUsage.status.in_(['denied', 'waiting_period', 'limit_exceeded', 'no_rule']),
            )
            .scalar()
        ) or 0
        rejection_rate = 0
        if total_usages:
            rejection_rate = round((denied_usages / total_usages) * 100, 2)

        metrics.append(
            {
                'plan': plan,
                'avg_cost': float(avg_cost or 0),
                'top_diagnosticos': [
                    {'descricao': diag or 'N/D', 'total': total}
                    for diag, total in diagnosticos
                ],
                'rejection_rate': rejection_rate,
            }
        )
    return metrics


def build_usage_history(plan_id: Optional[int] = None, subscription_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, object]]:
    query = HealthCoverageUsage.query.options(
        joinedload(HealthCoverageUsage.coverage),
        joinedload(HealthCoverageUsage.subscription).joinedload(HealthSubscription.plan),
        joinedload(HealthCoverageUsage.subscription).joinedload(HealthSubscription.animal),
    ).order_by(HealthCoverageUsage.created_at.desc())
    if subscription_id:
        query = query.filter(HealthCoverageUsage.subscription_id == subscription_id)
    if plan_id:
        query = query.join(HealthSubscription).filter(HealthSubscription.plan_id == plan_id)

    usages = []
    for usage in query.limit(limit).all():
        plan_name = usage.subscription.plan.name if usage.subscription and usage.subscription.plan else None
        animal_name = usage.subscription.animal.name if usage.subscription and usage.subscription.animal else None
        usages.append(
            {
                'id': usage.id,
                'status': usage.status,
                'status_label': coverage_label(usage.status),
                'amount_billed': float(usage.amount_billed or 0),
                'amount_covered': float(usage.amount_covered or 0),
                'coverage': usage.coverage.name if usage.coverage else None,
                'procedure_code': usage.coverage.procedure_code if usage.coverage else None,
                'plan': plan_name,
                'animal': animal_name,
                'created_at': usage.created_at.isoformat() if usage.created_at else None,
            }
        )
    return usages


def insurer_token_valid(token: Optional[str]) -> bool:
    expected = current_app.config.get('INSURER_PORTAL_TOKEN')
    if not expected:
        return True
    return token == expected
