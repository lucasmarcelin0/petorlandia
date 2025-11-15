"""Financial consolidation helpers for monthly clinic snapshots."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, List, Optional

from dateutil.relativedelta import relativedelta
from flask import current_app, has_app_context
from sqlalchemy import cast, func
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.sql.sqltypes import Numeric

import models
from extensions import db
from models import (
    BlocoOrcamento,
    ClinicFinancialSnapshot,
    Clinica,
    Consulta,
    Orcamento,
    OrcamentoItem,
    Order,
    OrderItem,
    Product,
    User,
)

ZERO = Decimal("0.00")
MANUAL_ENTRY_MODEL_CANDIDATES = (
    "ClinicManualFinancialEntry",
    "ClinicManualEntry",
    "ClinicFinancialEntry",
)
MANUAL_AMOUNT_FIELDS = ("valor", "amount", "valor_total")
MANUAL_DATE_FIELDS = ("data", "reference_date", "competencia", "occurred_at", "created_at")


def _log(message: str, *args) -> None:
    if has_app_context():
        current_app.logger.info(message, *args)
    else:  # pragma: no cover - only triggered outside flask contexts
        if args:
            message = message % args
        print(message)


def _ensure_decimal(value) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalize_month(target: Optional[date | datetime | str]) -> date:
    if target is None:
        base = date.today()
    elif isinstance(target, date) and not isinstance(target, datetime):
        base = target
    elif isinstance(target, datetime):
        base = target.date()
    elif isinstance(target, str):
        text = target.strip()
        fmt = "%Y-%m-%d" if len(text) > 7 else "%Y-%m"
        base = datetime.strptime(text, fmt).date()
    else:  # pragma: no cover - defensive branch
        raise ValueError("Unsupported month value")
    return base.replace(day=1)


def _month_range(month_start: date) -> tuple[datetime, datetime]:
    range_start = datetime.combine(month_start, datetime.min.time())
    range_end = datetime.combine(month_start + relativedelta(months=1), datetime.min.time())
    return range_start, range_end


def _service_revenue_total(clinic_id: int, start_dt: datetime, end_dt: datetime) -> Decimal:
    item_date = func.coalesce(
        Orcamento.created_at,
        Consulta.created_at,
        BlocoOrcamento.data_criacao,
    )
    total = (
        db.session.query(func.coalesce(func.sum(OrcamentoItem.valor), 0))
        .outerjoin(Orcamento, Orcamento.id == OrcamentoItem.orcamento_id)
        .outerjoin(Consulta, Consulta.id == OrcamentoItem.consulta_id)
        .outerjoin(BlocoOrcamento, BlocoOrcamento.id == OrcamentoItem.bloco_id)
        .filter(OrcamentoItem.clinica_id == clinic_id)
        .filter(item_date >= start_dt, item_date < end_dt)
        .scalar()
    )
    return _ensure_decimal(total)


def _order_clinic_filters(clinic_id: int):
    order_clinic_column = None
    if hasattr(Order, 'clinica_id'):
        order_clinic_column = Order.clinica_id
    elif hasattr(Order, 'clinic_id'):
        order_clinic_column = Order.clinic_id

    if order_clinic_column is not None:
        return [order_clinic_column == clinic_id]
    return [User.clinica_id == clinic_id]


def _product_revenue_total(clinic_id: int, start_dt: datetime, end_dt: datetime) -> Decimal:
    price_expr = func.coalesce(
        OrderItem.unit_price,
        cast(Product.price, Numeric(10, 2)),
        0,
    )
    quantity_expr = func.coalesce(OrderItem.quantity, 0)
    total_expr = func.sum(price_expr * quantity_expr)

    query = (
        db.session.query(func.coalesce(total_expr, 0))
        .join(Order, Order.id == OrderItem.order_id)
        .outerjoin(Product, Product.id == OrderItem.product_id)
        .outerjoin(User, User.id == Order.user_id)
        .filter(Order.created_at >= start_dt, Order.created_at < end_dt)
    )
    for clause in _order_clinic_filters(clinic_id):
        query = query.filter(clause)
    total = query.scalar()
    return _ensure_decimal(total)


def _resolve_manual_model():
    for name in MANUAL_ENTRY_MODEL_CANDIDATES:
        model = getattr(models, name, None)
        if model is not None:
            return model
    return None


def _resolve_column(model, candidates: Iterable[str]):
    for name in candidates:
        column = getattr(model, name, None)
        if column is not None:
            return column
    return None


def _manual_entries_total(clinic_id: int, start_dt: datetime, end_dt: datetime) -> Decimal:
    model = _resolve_manual_model()
    if model is None or not hasattr(model, 'clinic_id'):
        return ZERO

    amount_column = _resolve_column(model, MANUAL_AMOUNT_FIELDS)
    date_column = _resolve_column(model, MANUAL_DATE_FIELDS)
    if amount_column is None or date_column is None:
        return ZERO

    try:
        total = (
            db.session.query(func.coalesce(func.sum(amount_column), 0))
            .filter(model.clinic_id == clinic_id)
            .filter(date_column >= start_dt, date_column < end_dt)
            .scalar()
        )
    except (ProgrammingError, OperationalError):  # pragma: no cover - legacy DBs
        return ZERO
    return _ensure_decimal(total)


def generate_financial_snapshot(clinic_id: int, month: Optional[date | datetime | str] = None) -> ClinicFinancialSnapshot:
    """Create or refresh the snapshot for ``clinic_id`` in the given ``month``."""

    month_start = _normalize_month(month)
    range_start, range_end = _month_range(month_start)

    service_total = _service_revenue_total(clinic_id, range_start, range_end)
    product_total = _product_revenue_total(clinic_id, range_start, range_end)
    manual_total = _manual_entries_total(clinic_id, range_start, range_end)

    # Até que exista um campo próprio, consolide lançamentos manuais em serviços.
    service_total += manual_total

    snapshot = (
        ClinicFinancialSnapshot.query
        .filter_by(clinic_id=clinic_id, month=month_start)
        .one_or_none()
    )
    if snapshot is None:
        snapshot = ClinicFinancialSnapshot(clinic_id=clinic_id, month=month_start)
        db.session.add(snapshot)

    snapshot.total_receitas_servicos = service_total
    snapshot.total_receitas_produtos = product_total
    snapshot.gerado_em = datetime.utcnow()
    snapshot.refresh_totals()
    db.session.commit()

    _log(f"[Contabilidade] Snapshot gerado para Clínica {clinic_id} — Mês {month_start:%Y-%m}")
    return snapshot


def update_financial_snapshots_daily(
    target_month: Optional[date | datetime | str] = None,
    clinic_ids: Optional[Iterable[int]] = None,
) -> List[ClinicFinancialSnapshot]:
    """Rebuild snapshots for the current (or provided) month for all clinics."""

    month_start = _normalize_month(target_month)
    query = Clinica.query
    if clinic_ids:
        query = query.filter(Clinica.id.in_(list(clinic_ids)))

    snapshots: List[ClinicFinancialSnapshot] = []
    for clinic in query.order_by(Clinica.id).all():
        snapshots.append(generate_financial_snapshot(clinic.id, month_start))

    _log(
        "[Contabilidade] %s snapshot(s) atualizados — Mês %s",
        len(snapshots),
        f"{month_start:%Y-%m}",
    )
    return snapshots
