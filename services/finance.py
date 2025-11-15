"""Financial consolidation helpers for monthly clinic snapshots."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence, Tuple

from dateutil.relativedelta import relativedelta
from flask import current_app, has_app_context
from sqlalchemy import cast, func
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.sql.sqltypes import Numeric

import models
from extensions import db
from models import (
    BlocoOrcamento,
    ClassifiedTransaction,
    ClinicFinancialSnapshot,
    Clinica,
    Consulta,
    Orcamento,
    OrcamentoItem,
    Order,
    OrderItem,
    Product,
    ServicoClinica,
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
MANUAL_DESCRIPTION_FIELDS = ("descricao", "description", "detalhes", "notes", "titulo", "title")

VET_PAYMENT_MODEL_CANDIDATES = (
    "ClinicVeterinarianPayment",
    "VeterinarianPayment",
    "VetPayment",
)
VET_PAYMENT_DATE_FIELDS = ("data_pagamento", "paid_at", "data", "created_at")
VET_PAYMENT_AMOUNT_FIELDS = ("valor", "amount", "valor_total")
VET_PAYMENT_DESCRIPTION_FIELDS = ("descricao", "description", "detalhes")
VET_PAYMENT_INVOICE_FIELDS = ("nota_fiscal", "nf_number", "invoice_number")
VET_PAYMENT_RAW_FIELDS = ("external_id", "payment_id", "id")

EXPENSE_MODEL_CANDIDATES = (
    "ClinicExpense",
    "ClinicExpenseEntry",
    "ClinicExpenseItem",
    "ClinicPurchase",
)
EXPENSE_DATE_FIELDS = ("data", "occurred_at", "created_at", "reference_date")
EXPENSE_AMOUNT_FIELDS = ("valor", "amount", "valor_total", "total")
EXPENSE_NAME_FIELDS = ("nome", "descricao", "description", "item_name")
EXPENSE_KIND_FIELDS = ("tipo", "category", "natureza", "kind")
EXPENSE_COGS_FLAGS = ("eh_custo", "is_cogs", "is_inventory", "is_resale")


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


def _format_currency(value: Decimal) -> str:
    return f"R$ {value:.2f}"


def _prepare_description(description: Optional[str], fallback: str) -> str:
    text = (description or fallback or "").strip() or fallback or ""
    return text[:255]


def _prepare_subcategory(subcategory: Optional[str]) -> Optional[str]:
    if not subcategory:
        return None
    text = subcategory.strip()
    return text[:80] or None


def _ensure_datetime(value: Optional[datetime], default_date: date) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return datetime.combine(default_date, datetime.min.time())


def _upsert_classified_transaction(
    clinic_id: int,
    month_start: date,
    raw_id: str,
    *,
    date_value: datetime,
    origin: str,
    description: str,
    value: Decimal,
    category: str,
    subcategory: Optional[str] = None,
) -> Tuple[ClassifiedTransaction, bool]:
    record = (
        ClassifiedTransaction.query
        .filter_by(clinic_id=clinic_id, raw_id=raw_id)
        .one_or_none()
    )
    attrs = {
        'date': date_value,
        'month': month_start,
        'origin': origin,
        'description': description,
        'value': value,
        'category': category,
        'subcategory': subcategory,
    }
    changed = False
    if record is None:
        record = ClassifiedTransaction(clinic_id=clinic_id, raw_id=raw_id, **attrs)
        db.session.add(record)
        changed = True
    else:
        for key, new_value in attrs.items():
            if getattr(record, key) != new_value:
                setattr(record, key, new_value)
                changed = True
    return record, changed


def _classify_service_transactions(
    clinic_id: int,
    month_start: date,
    start_dt: datetime,
    end_dt: datetime,
) -> Tuple[List[ClassifiedTransaction], bool]:
    item_date_expr = func.coalesce(
        Orcamento.created_at,
        Consulta.created_at,
        BlocoOrcamento.data_criacao,
    )

    query = (
        db.session.query(
            OrcamentoItem.id.label('item_id'),
            item_date_expr.label('item_date'),
            OrcamentoItem.descricao.label('descricao'),
            OrcamentoItem.valor.label('valor'),
            ServicoClinica.descricao.label('servico_nome'),
        )
        .outerjoin(Orcamento, Orcamento.id == OrcamentoItem.orcamento_id)
        .outerjoin(Consulta, Consulta.id == OrcamentoItem.consulta_id)
        .outerjoin(BlocoOrcamento, BlocoOrcamento.id == OrcamentoItem.bloco_id)
        .outerjoin(ServicoClinica, ServicoClinica.id == OrcamentoItem.servico_id)
        .filter(OrcamentoItem.clinica_id == clinic_id)
        .filter(item_date_expr >= start_dt, item_date_expr < end_dt)
    )
    records: List[ClassifiedTransaction] = []
    changed = False
    for row in query.all():
        occurred_at = _ensure_datetime(row.item_date, month_start)
        value = _ensure_decimal(row.valor)
        description = _prepare_description(row.descricao, "Serviço")
        subcategory = _prepare_subcategory(row.servico_nome or row.descricao)
        record, record_changed = _upsert_classified_transaction(
            clinic_id,
            month_start,
            raw_id=f"service:{row.item_id}",
            date_value=occurred_at,
            origin="service",
            description=description,
            value=value,
            category="receita_servico",
            subcategory=subcategory,
        )
        records.append(record)
        changed = changed or record_changed
        _log(
            "[Contabilidade] Classificado: Serviço -> receita_servico (%s)",
            _format_currency(value),
        )
    return records, changed


def _classify_product_sales(
    clinic_id: int,
    month_start: date,
    start_dt: datetime,
    end_dt: datetime,
) -> Tuple[List[ClassifiedTransaction], bool]:
    query = (
        db.session.query(
            OrderItem.id.label('item_id'),
            Order.created_at.label('order_date'),
            OrderItem.item_name.label('item_name'),
            OrderItem.quantity.label('quantity'),
            OrderItem.unit_price.label('unit_price'),
            Product.name.label('product_name'),
            Product.price.label('product_price'),
            Product.mp_category_id.label('product_category'),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .outerjoin(Product, Product.id == OrderItem.product_id)
        .outerjoin(User, User.id == Order.user_id)
        .filter(Order.created_at >= start_dt, Order.created_at < end_dt)
    )
    for clause in _order_clinic_filters(clinic_id):
        query = query.filter(clause)

    records: List[ClassifiedTransaction] = []
    changed = False
    for row in query.all():
        occurred_at = _ensure_datetime(row.order_date, month_start)
        quantity = Decimal(row.quantity or 0)
        unit_price = _ensure_decimal(row.unit_price if row.unit_price is not None else row.product_price)
        value = unit_price * quantity
        description = _prepare_description(row.item_name or row.product_name, "Venda de produto")
        subcategory = _prepare_subcategory(row.product_category or row.product_name)
        record, record_changed = _upsert_classified_transaction(
            clinic_id,
            month_start,
            raw_id=f"product:{row.item_id}",
            date_value=occurred_at,
            origin="product_sale",
            description=description,
            value=value,
            category="receita_produto",
            subcategory=subcategory,
        )
        records.append(record)
        changed = changed or record_changed
        _log(
            "[Contabilidade] Classificado: Venda -> receita_produto (%s)",
            _format_currency(value),
        )
    return records, changed


def _classify_manual_entries(
    clinic_id: int,
    month_start: date,
    start_dt: datetime,
    end_dt: datetime,
) -> Tuple[List[ClassifiedTransaction], bool]:
    model = _resolve_manual_model()
    if model is None or not hasattr(model, 'clinic_id'):
        return [], False

    amount_column = _resolve_column(model, MANUAL_AMOUNT_FIELDS)
    date_column = _resolve_column(model, MANUAL_DATE_FIELDS)
    description_column = _resolve_column(model, MANUAL_DESCRIPTION_FIELDS)
    if amount_column is None or date_column is None:
        return [], False

    query = model.query.filter(model.clinic_id == clinic_id)
    query = query.filter(date_column >= start_dt, date_column < end_dt)

    records: List[ClassifiedTransaction] = []
    changed = False
    for entry in query.all():
        date_value = getattr(entry, date_column.key)
        amount_value = getattr(entry, amount_column.key)
        description = getattr(entry, description_column.key, None) if description_column else None
        value = _ensure_decimal(amount_value)
        record, record_changed = _upsert_classified_transaction(
            clinic_id,
            month_start,
            raw_id=f"manual:{getattr(entry, 'id', id(entry))}",
            date_value=_ensure_datetime(date_value, month_start),
            origin="manual",
            description=_prepare_description(description, "Lançamento manual"),
            value=value,
            category="receita_servico",
            subcategory=_prepare_subcategory("ajuste_manual"),
        )
        records.append(record)
        changed = changed or record_changed
        _log(
            "[Contabilidade] Classificado: Manual -> receita_servico (%s)",
            _format_currency(value),
        )
    return records, changed


def _resolve_optional_model(candidates: Sequence[str]):
    for name in candidates:
        model = getattr(models, name, None)
        if model is not None:
            return model
    return None


def _classify_veterinarian_payments(
    clinic_id: int,
    month_start: date,
    start_dt: datetime,
    end_dt: datetime,
) -> Tuple[List[ClassifiedTransaction], bool]:
    model = _resolve_optional_model(VET_PAYMENT_MODEL_CANDIDATES)
    if model is None or not hasattr(model, 'clinica_id'):
        return [], False

    amount_column = _resolve_column(model, VET_PAYMENT_AMOUNT_FIELDS)
    date_column = _resolve_column(model, VET_PAYMENT_DATE_FIELDS)
    description_column = _resolve_column(model, VET_PAYMENT_DESCRIPTION_FIELDS)
    invoice_column = _resolve_column(model, VET_PAYMENT_INVOICE_FIELDS)
    raw_column = _resolve_column(model, VET_PAYMENT_RAW_FIELDS)
    if amount_column is None or date_column is None:
        return [], False

    query = model.query.filter(model.clinica_id == clinic_id)
    query = query.filter(date_column >= start_dt, date_column < end_dt)

    records: List[ClassifiedTransaction] = []
    changed = False
    for entry in query.all():
        amount_value = getattr(entry, amount_column.key)
        date_value = getattr(entry, date_column.key)
        description = getattr(entry, description_column.key, "Pagamento PJ") if description_column else "Pagamento PJ"
        nf_value = getattr(entry, invoice_column.key, None) if invoice_column else None
        if nf_value:
            description = f"{description} - NF {nf_value}"
        raw_value = getattr(entry, raw_column.key, getattr(entry, 'id', None)) if raw_column else getattr(entry, 'id', None)
        if raw_value is None:
            raw_value = id(entry)
        record, record_changed = _upsert_classified_transaction(
            clinic_id,
            month_start,
            raw_id=f"vet_payment:{raw_value}",
            date_value=_ensure_datetime(date_value, month_start),
            origin="vet_payment",
            description=_prepare_description(description, "Pagamento PJ"),
            value=_ensure_decimal(amount_value),
            category="pagamento_pj",
            subcategory=_prepare_subcategory("prestador_servico"),
        )
        records.append(record)
        changed = changed or record_changed
        _log(
            "[Contabilidade] Classificado: Pagamento PJ -> pagamento_pj (%s)",
            _format_currency(record.value),
        )
    return records, changed


def _detect_expense_category(entry, kind_field, cogs_flag_field) -> str:
    if cogs_flag_field:
        flag_value = getattr(entry, cogs_flag_field.key, None)
        if isinstance(flag_value, bool) and flag_value:
            return "custo_produto"
    if kind_field:
        kind_text = (getattr(entry, kind_field.key, "") or "").lower()
        if "produto" in kind_text or "estoque" in kind_text or "revenda" in kind_text:
            return "custo_produto"
    return "despesa_insumo"


def _classify_expenses(
    clinic_id: int,
    month_start: date,
    start_dt: datetime,
    end_dt: datetime,
) -> Tuple[List[ClassifiedTransaction], bool]:
    model = _resolve_optional_model(EXPENSE_MODEL_CANDIDATES)
    if model is None or not hasattr(model, 'clinica_id'):
        return [], False

    amount_column = _resolve_column(model, EXPENSE_AMOUNT_FIELDS)
    date_column = _resolve_column(model, EXPENSE_DATE_FIELDS)
    name_column = _resolve_column(model, EXPENSE_NAME_FIELDS)
    kind_column = _resolve_column(model, EXPENSE_KIND_FIELDS)
    cogs_flag = _resolve_column(model, EXPENSE_COGS_FLAGS)
    if amount_column is None or date_column is None:
        return [], False

    query = model.query.filter(model.clinica_id == clinic_id)
    query = query.filter(date_column >= start_dt, date_column < end_dt)

    records: List[ClassifiedTransaction] = []
    changed = False
    for entry in query.all():
        amount_value = getattr(entry, amount_column.key)
        date_value = getattr(entry, date_column.key)
        description = getattr(entry, name_column.key, "Despesa") if name_column else "Despesa"
        category = _detect_expense_category(entry, kind_column, cogs_flag)
        subcategory = description
        raw_value = getattr(entry, 'id', id(entry))
        record, record_changed = _upsert_classified_transaction(
            clinic_id,
            month_start,
            raw_id=f"expense:{raw_value}",
            date_value=_ensure_datetime(date_value, month_start),
            origin="expense",
            description=_prepare_description(description, "Despesa"),
            value=_ensure_decimal(amount_value),
            category=category,
            subcategory=_prepare_subcategory(subcategory),
        )
        records.append(record)
        changed = changed or record_changed
        _log(
            "[Contabilidade] Classificado: Despesa -> %s (%s)",
            category,
            _format_currency(record.value),
        )
    return records, changed


def classify_transactions_for_month(
    clinic_id: int,
    month: Optional[date | datetime | str] = None,
) -> List[ClassifiedTransaction]:
    month_start = _normalize_month(month)
    start_dt, end_dt = _month_range(month_start)

    handlers = (
        _classify_service_transactions,
        _classify_product_sales,
        _classify_manual_entries,
        _classify_veterinarian_payments,
        _classify_expenses,
    )

    records: List[ClassifiedTransaction] = []
    changed = False
    for handler in handlers:
        handler_records, handler_changed = handler(clinic_id, month_start, start_dt, end_dt)
        records.extend(handler_records)
        changed = changed or handler_changed

    if changed:
        db.session.commit()
    return records


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

    classify_transactions_for_month(clinic_id, month_start)
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
