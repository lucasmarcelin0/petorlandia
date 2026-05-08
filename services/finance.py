"""Financial consolidation helpers for monthly clinic snapshots."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from dateutil.relativedelta import relativedelta
from flask import current_app, has_app_context
from sqlalchemy import and_, cast, func, or_, inspect as sa_inspect
from sqlalchemy.exc import NoSuchTableError, OperationalError, ProgrammingError
from sqlalchemy.orm import load_only
from sqlalchemy.sql.sqltypes import Numeric

import models
from extensions import db
from models import (
    AccountingAccount,
    BankStatementTransaction,
    BlocoOrcamento,
    ClassifiedTransaction,
    ClinicFinancialSnapshot,
    ClinicNotification,
    ClinicTaxes,
    Clinica,
    Consulta,
    FiscalDocument,
    FiscalDocumentStatus,
    Orcamento,
    OrcamentoItem,
    Order,
    OrderItem,
    PJPayment,
    Product,
    ServicoClinica,
    User,
)
from time_utils import utcnow

ZERO = Decimal("0.00")
_TABLE_COLUMN_CACHE: dict[str, set[str]] = {}
REQUIRED_PJ_PAYMENT_COLUMNS = {"tipo_prestador", "plantao_horas"}
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
    "PJPayment",
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


def _normalize_prestador_type(raw_value: Optional[str]) -> str:
    text = (raw_value or "").strip().lower()
    if not text:
        return ""
    if "planton" in text:
        return "plantonista"
    if "especial" in text or "cirurg" in text:
        return "especialista"
    if "demais" in text or "outro" in text:
        return "demais_pj"
    return text


def determine_pj_payment_subcategory(raw_value: Optional[str]) -> str:
    normalized = _normalize_prestador_type(raw_value)
    if not normalized:
        return "prestador_servico"
    return normalized.replace(" ", "_")

REVENUE_CATEGORIES = ("receita_servico", "receita_produto")
PAYROLL_CATEGORIES = (
    "folha_pagamento",
    "pro_labore",
    "pagamento_pj",
    "remuneracao",
    "salario",
)
DEFAULT_ISS_RATE = Decimal("0.05")
VET_WITHHOLDING_RATE = Decimal("0.05")
PLANTONISTA_RETENTION_RATE = VET_WITHHOLDING_RATE
PLANTAO_PENDING_ALERT_DAYS = 5
PJ_WITHHOLDING_THRESHOLD = Decimal("10000.00")
CURRENCY_PLACES = Decimal("0.01")
FACTOR_PLACES = Decimal("0.0001")
SIMPLIES_ANEXO_III_BRACKETS = (
    (Decimal("180000"), Decimal("0.06"), Decimal("0")),
    (Decimal("360000"), Decimal("0.112"), Decimal("9360")),
    (Decimal("720000"), Decimal("0.135"), Decimal("17640")),
    (Decimal("1800000"), Decimal("0.16"), Decimal("35640")),
    (Decimal("3600000"), Decimal("0.21"), Decimal("125640")),
    (Decimal("4800000"), Decimal("0.33"), Decimal("648000")),
)


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


def _quantize_currency(value: Decimal) -> Decimal:
    return _ensure_decimal(value).quantize(CURRENCY_PLACES, rounding=ROUND_HALF_UP)


def _quantize_factor(value: Decimal) -> Decimal:
    return _ensure_decimal(value).quantize(FACTOR_PLACES, rounding=ROUND_HALF_UP)


def _normalize_percentage(value) -> Decimal:
    rate = _ensure_decimal(value if value is not None else DEFAULT_ISS_RATE)
    if rate > 1:
        rate = rate / Decimal("100")
    return rate


def _clinic_is_simples(clinic: Clinica) -> bool:
    regime = getattr(clinic, 'regime_tributario', None)
    if regime is None:
        return True
    text = str(regime).strip().lower()
    return text in {'simples', 'simples_nacional', 'sn', 'anexo_iii', 'anexo_v'}


def _determine_simples_bracket(revenue_12m: Decimal) -> int | None:
    revenue = _ensure_decimal(revenue_12m)
    for idx, (limit, _rate, _deduction) in enumerate(SIMPLIES_ANEXO_III_BRACKETS, start=1):
        if revenue <= limit:
            return idx
    return len(SIMPLIES_ANEXO_III_BRACKETS) if revenue > ZERO else None


def _effective_simples_rate(revenue_12m: Decimal, faixa: int | None) -> Decimal:
    revenue = _ensure_decimal(revenue_12m)
    if not faixa or faixa < 1 or faixa > len(SIMPLIES_ANEXO_III_BRACKETS) or revenue <= ZERO:
        return ZERO
    _, nominal_rate, deduction = SIMPLIES_ANEXO_III_BRACKETS[faixa - 1]
    return ((revenue * nominal_rate) - deduction) / revenue


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


def _classified_sum_for_month(clinic_id: int, month_start: date, categories: Sequence[str]) -> Decimal:
    if not categories:
        return ZERO
    total = (
        db.session.query(func.coalesce(func.sum(ClassifiedTransaction.value), 0))
        .filter(ClassifiedTransaction.clinic_id == clinic_id)
        .filter(ClassifiedTransaction.month == month_start)
        .filter(ClassifiedTransaction.category.in_(list(categories)))
        .scalar()
    )
    return _ensure_decimal(total)


def _classified_sum_for_range(
    clinic_id: int,
    month_start: date,
    categories: Sequence[str],
    months: int = 12,
) -> Decimal:
    if not categories or months <= 0:
        return ZERO
    window_start = month_start - relativedelta(months=months - 1)
    window_end = month_start + relativedelta(months=1)
    total = (
        db.session.query(func.coalesce(func.sum(ClassifiedTransaction.value), 0))
        .filter(ClassifiedTransaction.clinic_id == clinic_id)
        .filter(ClassifiedTransaction.month >= window_start)
        .filter(ClassifiedTransaction.month < window_end)
        .filter(ClassifiedTransaction.category.in_(list(categories)))
        .scalar()
    )
    return _ensure_decimal(total)


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


def _get_table_columns(table_name: str) -> set[str]:
    if not table_name:
        return set()
    if table_name in _TABLE_COLUMN_CACHE:
        return _TABLE_COLUMN_CACHE[table_name]
    try:
        bind = db.session.connection() if db.session.is_active else db.engine
        inspector = sa_inspect(bind)
        names = {column["name"] for column in inspector.get_columns(table_name)}
    except (ProgrammingError, OperationalError, NoSuchTableError):  # pragma: no cover - legacy DBs
        names = set()
    _TABLE_COLUMN_CACHE[table_name] = names
    return names


def _table_has_column(table_name: str, column_name: str) -> bool:
    if not column_name:
        return False
    return column_name in _get_table_columns(table_name)


def pj_payments_schema_is_ready() -> bool:
    """Return ``True`` when ``pj_payments`` already exposes the new columns."""

    columns = _get_table_columns('pj_payments')
    return REQUIRED_PJ_PAYMENT_COLUMNS.issubset(columns)


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
        clinic = db.session.get(Clinica, clinic_id)
        record = ClassifiedTransaction(clinic=clinic, clinic_id=clinic_id, raw_id=raw_id, **attrs)
        db.session.add(record)
        changed = True
    else:
        for key, new_value in attrs.items():
            if getattr(record, key) != new_value:
                setattr(record, key, new_value)
                changed = True
    if record.clinic is None:
        record.clinic = db.session.get(Clinica, clinic_id)
    if record.clinic is not None and record not in record.clinic.classified_transactions:
        record.clinic.classified_transactions.append(record)
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
    service_date_column = getattr(model, 'data_servico', None)
    table_name = getattr(model, '__tablename__', None)
    service_date_available = False
    if service_date_column is not None and table_name:
        service_date_available = _table_has_column(table_name, service_date_column.key)
        if not service_date_available:
            service_date_column = None

    if (
        service_date_column is not None
        and service_date_available
        and service_date_column.key != date_column.key
    ):
        query = query.filter(
            or_(
                and_(date_column >= start_dt, date_column < end_dt),
                and_(
                    date_column.is_(None),
                    service_date_column >= start_dt,
                    service_date_column < end_dt,
                ),
            )
        )
    else:
        query = query.filter(date_column >= start_dt, date_column < end_dt)

    provider_type_column = getattr(model, 'tipo_prestador', None)
    provider_type_available = False
    if provider_type_column is not None and table_name:
        provider_type_available = _table_has_column(table_name, provider_type_column.key)
        if not provider_type_available:
            _log(
                "[Contabilidade] Campo tipo_prestador ausente na tabela %s; usando subcategoria padrão",
                table_name,
            )

    load_only_columns = []
    for column in (
        amount_column,
        date_column,
        description_column,
        invoice_column,
        raw_column,
    ):
        if column is not None and column not in load_only_columns:
            load_only_columns.append(column)
    id_column = getattr(model, 'id', None)
    if id_column is not None and id_column not in load_only_columns:
        load_only_columns.append(id_column)
    if provider_type_available and provider_type_column not in load_only_columns:
        load_only_columns.append(provider_type_column)
    if service_date_column is not None and service_date_column not in load_only_columns:
        load_only_columns.append(service_date_column)
    if load_only_columns:
        query = query.options(load_only(*load_only_columns))

    records: List[ClassifiedTransaction] = []
    changed = False
    for entry in query.all():
        amount_value = getattr(entry, amount_column.key)
        date_value = getattr(entry, date_column.key)
        if not date_value and service_date_column is not None:
            date_value = getattr(entry, service_date_column.key)
        description = getattr(entry, description_column.key, "Pagamento PJ") if description_column else "Pagamento PJ"
        nf_value = getattr(entry, invoice_column.key, None) if invoice_column else None
        if nf_value:
            description = f"{description} - NF {nf_value}"
        raw_value = getattr(entry, raw_column.key, getattr(entry, 'id', None)) if raw_column else getattr(entry, 'id', None)
        if raw_value is None:
            raw_value = id(entry)
        provider_value = (
            getattr(entry, provider_type_column.key, None)
            if provider_type_available and provider_type_column is not None
            else None
        )
        provider_type = determine_pj_payment_subcategory(provider_value)
        record, record_changed = _upsert_classified_transaction(
            clinic_id,
            month_start,
            raw_id=f"vet_payment:{raw_value}",
            date_value=_ensure_datetime(date_value, month_start),
            origin="vet_payment",
            description=_prepare_description(description, "Pagamento PJ"),
            value=_ensure_decimal(amount_value),
            category="pagamento_pj",
            subcategory=_prepare_subcategory(provider_type),
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
        if handler_changed:
            db.session.flush()

    if changed:
        db.session.commit()
    return records


@dataclass
class HistoryBackfillFailure:
    clinic_id: int
    month: date
    error: str


@dataclass
class HistoryBackfillResult:
    processed: int
    clinics: list[int]
    months: list[date]
    failures: list[HistoryBackfillFailure]


def run_transactions_history_backfill(
    months: int,
    reference_month: Optional[date | datetime | str] = None,
    clinic_ids: Optional[Iterable[int]] = None,
    progress_callback: Optional[Callable[[int, date], None]] = None,
    error_callback: Optional[Callable[[int, date, Exception], None]] = None,
) -> HistoryBackfillResult:
    """Execute classification for multiple clinics/months returning a summary."""

    if months <= 0:
        raise ValueError("O número de meses deve ser maior que zero.")

    base_month = _normalize_month(reference_month)
    month_starts = sorted(
        base_month - relativedelta(months=offset)
        for offset in range(months)
    )

    query = Clinica.query
    if clinic_ids:
        query = query.filter(Clinica.id.in_(list(clinic_ids)))
    clinics = query.order_by(Clinica.id.asc()).all()
    clinic_ids_list = [clinic.id for clinic in clinics]
    if not clinic_ids_list:
        return HistoryBackfillResult(0, [], month_starts, [])

    failures: list[HistoryBackfillFailure] = []
    processed = 0
    for clinic in clinics:
        for month_start in month_starts:
            try:
                classify_transactions_for_month(clinic.id, month_start)
                processed += 1
                if progress_callback:
                    progress_callback(clinic.id, month_start)
            except Exception as exc:  # pragma: no cover - defensive logging
                db.session.rollback()
                _log(
                    "[Backfill] Falha ao classificar clínica %s no mês %s: %s",
                    clinic.id,
                    f"{month_start:%Y-%m}",
                    exc,
                )
                failures.append(HistoryBackfillFailure(clinic.id, month_start, str(exc)))
                if error_callback:
                    error_callback(clinic.id, month_start, exc)
    return HistoryBackfillResult(processed, clinic_ids_list, month_starts, failures)


def _plantonista_retention_rate(clinic: Clinica | None) -> Decimal:
    if clinic is None:
        return _normalize_percentage(PLANTONISTA_RETENTION_RATE)
    candidate = getattr(clinic, 'aliquota_retencao_plantonista', None)
    if candidate in (None, ''):
        candidate = getattr(clinic, 'retencao_plantonista_percentual', None)
    if candidate in (None, ''):
        candidate = PLANTONISTA_RETENTION_RATE
    return _normalize_percentage(candidate)


def _calculate_pj_withholding(clinic: Clinica, month_start: date) -> Decimal:
    if not clinic or not clinic.id:
        return ZERO
    if not pj_payments_schema_is_ready():
        _log(
            "[Tributário] Retenção PJ ignorada porque a coluna tipo_prestador não existe"
        )
        return ZERO
    month_end = month_start + relativedelta(months=1)
    total = ZERO
    municipal_requirement = bool(getattr(clinic, 'retencao_pj_obrigatoria', False))
    payments = PJPayment.query.filter(PJPayment.clinic_id == clinic.id).all()
    for payment in payments:
        reference_date = payment.data_pagamento or payment.data_servico
        if not reference_date or reference_date < month_start or reference_date >= month_end:
            continue
        value = _ensure_decimal(payment.valor)
        if value <= ZERO:
            continue
        provider_type = determine_pj_payment_subcategory(getattr(payment, 'tipo_prestador', None))
        rate = VET_WITHHOLDING_RATE
        requires_retention = (
            municipal_requirement
            or getattr(payment, 'retencao_obrigatoria', False)
            or value >= PJ_WITHHOLDING_THRESHOLD
        )
        if provider_type == 'plantonista':
            rate = _plantonista_retention_rate(clinic)
            requires_retention = True
        if not requires_retention:
            continue
        total += value * rate
    return _quantize_currency(total)


def _ensure_pending_plantao_notifications(
    clinic: Clinica,
    month_start: date,
    overdue_days: int = PLANTAO_PENDING_ALERT_DAYS,
) -> None:
    if not clinic or not clinic.id:
        return
    if not pj_payments_schema_is_ready():
        _log(
            "[Notificações] Plantões pendentes ignorados porque a coluna tipo_prestador não existe"
        )
        return
    try:
        overdue_days = int(overdue_days)
    except (TypeError, ValueError):
        overdue_days = PLANTAO_PENDING_ALERT_DAYS
    overdue_days = max(overdue_days, 1)
    title = "Plantão pendente"
    today = date.today()
    month_end = month_start + relativedelta(months=1)
    threshold = today - timedelta(days=overdue_days)
    query = (
        PJPayment.query
        .filter(PJPayment.clinic_id == clinic.id)
        .filter(PJPayment.data_servico >= month_start)
        .filter(PJPayment.data_servico < month_end)
        .filter(PJPayment.data_servico <= threshold)
        .filter(func.lower(func.coalesce(PJPayment.tipo_prestador, '')) == 'plantonista')
        .filter(or_(PJPayment.status.is_(None), PJPayment.status != 'pago'))
    )
    active_ids: set[int] = set()
    for payment in query.all():
        if not payment.data_servico:
            continue
        active_ids.add(payment.id)
        prefix = f"[PJPayment:{payment.id}]"
        days_overdue = max((today - payment.data_servico).days, overdue_days)
        message = (
            f"{prefix} Plantão de {payment.prestador_nome} em "
            f"{payment.data_servico.strftime('%d/%m/%Y')} segue pendente há {days_overdue} dia(s)."
        )
        existing = (
            ClinicNotification.query.filter_by(
                clinic_id=clinic.id,
                month=month_start,
                title=title,
            )
            .filter(ClinicNotification.message.like(f"{prefix}%"))
            .one_or_none()
        )
        if existing:
            existing.message = message
            if existing.resolved:
                existing.resolved = False
                existing.resolution_date = None
            continue
        db.session.add(
            ClinicNotification(
                clinic_id=clinic.id,
                month=month_start,
                title=title,
                message=message,
                type='warning',
            )
        )

    stale_notices = (
        ClinicNotification.query.filter_by(
            clinic_id=clinic.id,
            month=month_start,
            title=title,
        )
        .filter(ClinicNotification.message.like('[PJPayment:%'))
        .all()
    )
    for notice in stale_notices:
        marker = (notice.message or '').split(']')[0]
        if not marker.startswith('[PJPayment:'):
            continue
        try:
            payment_id = int(marker.split(':', 1)[1])
        except (ValueError, IndexError):
            continue
        if payment_id not in active_ids and not notice.resolved:
            notice.resolved = True
            notice.resolution_date = utcnow()


def calculate_clinic_taxes(
    clinic_id: int,
    month: Optional[date | datetime | str] = None,
) -> ClinicTaxes:
    month_start = _normalize_month(month)
    clinic = Clinica.query.get(clinic_id)
    if clinic is None:
        raise ValueError(f"Clinic {clinic_id} not found")

    service_revenue = _classified_sum_for_month(clinic_id, month_start, ("receita_servico",))
    monthly_revenue = _classified_sum_for_month(clinic_id, month_start, REVENUE_CATEGORIES)
    revenue_12m = _classified_sum_for_range(clinic_id, month_start, REVENUE_CATEGORIES)
    payroll_12m = _classified_sum_for_range(clinic_id, month_start, PAYROLL_CATEGORIES)

    iss_rate = _normalize_percentage(getattr(clinic, 'aliquota_iss', DEFAULT_ISS_RATE))
    iss_total = _quantize_currency(service_revenue * iss_rate)

    faixa_simples = _determine_simples_bracket(revenue_12m)
    das_total = ZERO
    if _clinic_is_simples(clinic) and faixa_simples:
        aliquota_efetiva = _effective_simples_rate(revenue_12m, faixa_simples)
        if aliquota_efetiva > ZERO and monthly_revenue > ZERO:
            das_total = _quantize_currency(monthly_revenue * aliquota_efetiva)

    retencoes_pj = _calculate_pj_withholding(clinic, month_start)
    fator_r = ZERO
    if revenue_12m > ZERO and payroll_12m > ZERO:
        fator_r = _quantize_factor(payroll_12m / revenue_12m)

    projecao_anual = _quantize_currency(monthly_revenue * Decimal(12)) if monthly_revenue > ZERO else ZERO

    taxes = (
        ClinicTaxes.query.filter_by(clinic_id=clinic_id, month=month_start).one_or_none()
    )
    if taxes is None:
        taxes = ClinicTaxes(clinic_id=clinic_id, month=month_start)
        db.session.add(taxes)

    taxes.iss_total = iss_total
    taxes.das_total = das_total
    taxes.retencoes_pj = retencoes_pj
    taxes.fator_r = fator_r
    taxes.faixa_simples = faixa_simples
    taxes.projecao_anual = projecao_anual
    overdue_days = getattr(clinic, 'plantao_alerta_dias', None)
    if overdue_days in (None, ''):
        overdue_days = getattr(clinic, 'dias_alerta_plantonista', None)
    if overdue_days in (None, ''):
        overdue_days = PLANTAO_PENDING_ALERT_DAYS
    _ensure_pending_plantao_notifications(clinic, month_start, overdue_days)
    db.session.commit()

    _log("[Tributário] ISS calculado: %s", _format_currency(iss_total))
    _log("[Tributário] DAS (Simples) calculado: %s", _format_currency(das_total))
    _log("[Tributário] Retenções sobre PJ: %s", _format_currency(retencoes_pj))
    _log("[Tributário] Fator R: %.4f", float(fator_r))

    return taxes


def generate_clinic_notifications(
    clinic_id: int,
    month: Optional[date | datetime | str] = None,
) -> List[ClinicNotification]:
    """Build or refresh accounting alerts for the requested clinic/month."""

    month_start = _normalize_month(month)
    clinic = Clinica.query.get(clinic_id)
    if clinic is None:
        raise ValueError(f"Clinic {clinic_id} not found")

    month_label = month_start.strftime("%m/%Y")
    month_end = month_start + relativedelta(months=1)
    taxes = ClinicTaxes.query.filter_by(clinic_id=clinic_id, month=month_start).one_or_none()
    revenue_12m = _classified_sum_for_range(clinic_id, month_start, REVENUE_CATEGORIES)

    alerts: list[dict[str, str]] = []

    def _add_alert(title: str, message: str, type_: str) -> None:
        alerts.append({"title": title, "message": message, "type": type_})

    if taxes and taxes.faixa_simples:
        faixa_index = max(1, min(int(taxes.faixa_simples), len(SIMPLIES_ANEXO_III_BRACKETS))) - 1
        faixa_limit = SIMPLIES_ANEXO_III_BRACKETS[faixa_index][0]
        if faixa_limit > ZERO:
            threshold = faixa_limit * Decimal("0.85")
            if revenue_12m >= threshold and revenue_12m < faixa_limit:
                _add_alert(
                    "Atenção: Receita próxima de mudar de faixa do Simples",
                    "O faturamento acumulado em 12 meses está acima de 85% do limite atual.",
                    "warning",
                )

    if taxes:
        fator_r_value = _ensure_decimal(getattr(taxes, 'fator_r', ZERO))
        if fator_r_value < Decimal("0.28"):
            _add_alert(
                "Fator R abaixo do limite",
                "Seu Fator R está baixo; os prestadores podem ser tributados no Anexo V.",
                "danger",
            )

        projecao = _ensure_decimal(getattr(taxes, 'projecao_anual', ZERO))
        if projecao > Decimal("4800000"):
            _add_alert(
                "Projeção anual acima do limite do Simples Nacional",
                "A projeção anual de receitas ultrapassa R$ 4,8 milhões e pode exigir migração de regime.",
                "danger",
            )

        iss_total = _ensure_decimal(getattr(taxes, 'iss_total', ZERO))
        if iss_total > ZERO:
            _add_alert(
                "ISS do mês pendente",
                f"Valor estimado de ISS para {month_label} ainda não está registrado como pago.",
                "info",
            )

        das_total = _ensure_decimal(getattr(taxes, 'das_total', ZERO))
        if das_total > ZERO:
            _add_alert(
                "DAS do mês pendente",
                f"O DAS calculado para {month_label} ainda não consta como quitado.",
                "info",
            )

    pj_payments_ready = pj_payments_schema_is_ready()
    payments_current: list[PJPayment] = []
    recent_payments: list[PJPayment] = []
    if pj_payments_ready:
        payments_current = (
            PJPayment.query
            .filter(PJPayment.clinic_id == clinic_id)
            .filter(PJPayment.data_servico >= month_start)
            .filter(PJPayment.data_servico < month_end)
            .all()
        )
        lookback_start = month_start - relativedelta(months=2)
        recent_payments = (
            PJPayment.query
            .filter(PJPayment.clinic_id == clinic_id)
            .filter(PJPayment.data_servico >= lookback_start)
            .filter(PJPayment.data_servico < month_end)
            .all()
        )
    else:
        _log(
            "[Notificações] Alertas de PJ ignorados porque a coluna tipo_prestador não existe"
        )

    provider_counts: dict[str, int] = defaultdict(int)
    provider_names: dict[str, str] = {}
    for payment in payments_current:
        provider_key = payment.prestador_cnpj or payment.prestador_nome or str(payment.id)
        provider_counts[provider_key] += 1
        provider_names[provider_key] = payment.prestador_nome or payment.prestador_cnpj or "Prestador"
        nf_number = (payment.nota_fiscal_numero or "").strip()
        if not nf_number:
            _add_alert(
                "Prestador sem nota fiscal",
                (
                    f"{provider_names[provider_key]} recebeu {_format_currency(_ensure_decimal(payment.valor))} "
                    f"em {payment.data_servico.strftime('%d/%m/%Y')} sem nota fiscal registrada."
                ),
                "danger",
            )

    monthly_totals: dict[str, dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for payment in recent_payments:
        if not payment.data_servico:
            continue
        provider_key = payment.prestador_cnpj or payment.prestador_nome or str(payment.id)
        provider_names[provider_key] = payment.prestador_nome or payment.prestador_cnpj or "Prestador"
        month_bucket = payment.data_servico.replace(day=1)
        monthly_totals[provider_key][month_bucket] += _ensure_decimal(payment.valor)

    risk_flags: dict[str, list[str]] = defaultdict(list)
    for provider_key, count in provider_counts.items():
        if count > 20:
            risk_flags[provider_key].append("mais de 20 repasses no mês")

    for provider_key, totals in monthly_totals.items():
        if len(totals) >= 3:
            values = [total for _month, total in sorted(totals.items())][-3:]
            if len(values) == 3 and len({value for value in values if value > ZERO}) == 1:
                risk_flags[provider_key].append("pagamentos idênticos nos últimos meses")

    for provider_key, reasons in risk_flags.items():
        if not reasons:
            continue
        provider_name = provider_names.get(provider_key, "Prestador")
        details = ", ".join(reasons)
        _add_alert(
            "Possível risco trabalhista com prestador PJ",
            f"{provider_name} apresenta {details} em {month_label}.",
            "warning",
        )

    negative_revenues = (
        db.session.query(func.count(ClassifiedTransaction.id))
        .filter(ClassifiedTransaction.clinic_id == clinic_id)
        .filter(ClassifiedTransaction.month == month_start)
        .filter(ClassifiedTransaction.category.in_(list(REVENUE_CATEGORIES)))
        .filter(ClassifiedTransaction.value < 0)
        .scalar()
    )
    if negative_revenues:
        _add_alert(
            "Receitas negativas ou inconsistentes",
            "Foram detectados lançamentos de receita com valores negativos para o mês.",
            "warning",
        )

    existing = ClinicNotification.query.filter_by(clinic_id=clinic_id, month=month_start).all()
    existing_map = {
        (notice.title, notice.type, notice.message or ""): notice
        for notice in existing
    }
    seen_keys: set[tuple[str, str, str]] = set()
    now = utcnow()

    for alert in alerts:
        message = alert.get("message", "")
        key = (alert["title"], alert["type"], message)
        seen_keys.add(key)
        if key in existing_map:
            notice = existing_map[key]
            notice.message = message
            if notice.resolved:
                notice.resolved = False
                notice.resolution_date = None
        else:
            db.session.add(
                ClinicNotification(
                    clinic_id=clinic_id,
                    month=month_start,
                    title=alert["title"],
                    message=message,
                    type=alert["type"],
                    created_at=now,
                )
            )

    for notice in existing:
        key = (notice.title, notice.type, notice.message or "")
        if key not in seen_keys and not notice.resolved:
            notice.resolved = True
            notice.resolution_date = now

    db.session.commit()
    return (
        ClinicNotification.query
        .filter_by(clinic_id=clinic_id, month=month_start, resolved=False)
        .order_by(ClinicNotification.created_at.desc())
        .all()
    )


def _sum_categories(clinic_id: int, month_start: date, categories: Sequence[str]) -> Decimal:
    return _classified_sum_for_month(clinic_id, month_start, categories)


def build_dre_report(
    clinic_id: int,
    month: Optional[date | datetime | str] = None,
    period: str = "monthly",
) -> dict:
    """Return a DRE-style result statement for monthly, quarterly or annual views."""

    month_start = _normalize_month(month)
    period = (period or "monthly").lower()
    if period == "quarterly":
        months = [month_start - relativedelta(months=offset) for offset in range(2, -1, -1)]
    elif period == "annual":
        months = [month_start - relativedelta(months=offset) for offset in range(11, -1, -1)]
    else:
        months = [month_start]

    rows = []
    totals = defaultdict(Decimal)
    for item_month in months:
        classify_transactions_for_month(clinic_id, item_month)
        taxes = calculate_clinic_taxes(clinic_id, item_month)
        receitas_servicos = _sum_categories(clinic_id, item_month, ("receita_servico",))
        receitas_produtos = _sum_categories(clinic_id, item_month, ("receita_produto",))
        impostos = _ensure_decimal(taxes.iss_total) + _ensure_decimal(taxes.das_total)
        custos_produtos = _sum_categories(clinic_id, item_month, ("custo_produto",))
        despesas_fixas = _sum_categories(
            clinic_id,
            item_month,
            ("despesa_fixa", "despesa_insumo", "folha_pagamento", "pagamento_pj"),
        )
        receita_bruta = receitas_servicos + receitas_produtos
        lucro_bruto = receita_bruta - impostos - custos_produtos
        resultado = lucro_bruto - despesas_fixas
        row = {
            "month": item_month,
            "receitas_servicos": _quantize_currency(receitas_servicos),
            "receitas_produtos": _quantize_currency(receitas_produtos),
            "receita_bruta": _quantize_currency(receita_bruta),
            "impostos": _quantize_currency(impostos),
            "custos_produtos": _quantize_currency(custos_produtos),
            "despesas_fixas": _quantize_currency(despesas_fixas),
            "lucro_bruto": _quantize_currency(lucro_bruto),
            "resultado_liquido": _quantize_currency(resultado),
        }
        rows.append(row)
        for key, value in row.items():
            if key != "month":
                totals[key] += _ensure_decimal(value)

    return {
        "clinic_id": clinic_id,
        "period": period,
        "start_month": months[0],
        "end_month": months[-1],
        "rows": rows,
        "totals": {key: _quantize_currency(value) for key, value in totals.items()},
    }


def build_cash_flow_report(
    clinic_id: int,
    month: Optional[date | datetime | str] = None,
) -> dict:
    """Return realized cash flow plus 30/60/90 day receivable/payable projections."""

    month_start = _normalize_month(month)
    month_end = month_start + relativedelta(months=1)
    classify_transactions_for_month(clinic_id, month_start)
    entradas = _sum_categories(clinic_id, month_start, REVENUE_CATEGORIES)
    saidas = _sum_categories(
        clinic_id,
        month_start,
        ("custo_produto", "despesa_fixa", "despesa_insumo", "folha_pagamento", "pagamento_pj"),
    )

    today = date.today()
    buckets = {
        "30": (today, today + timedelta(days=30)),
        "60": (today + timedelta(days=31), today + timedelta(days=60)),
        "90": (today + timedelta(days=61), today + timedelta(days=90)),
    }
    projections: dict[str, dict[str, Decimal]] = {}
    for label, (start, end) in buckets.items():
        receivables = (
            db.session.query(func.coalesce(func.sum(AccountingAccount.net_amount), 0))
            .filter(AccountingAccount.clinic_id == clinic_id)
            .filter(AccountingAccount.kind == "receivable")
            .filter(AccountingAccount.status == "open")
            .filter(AccountingAccount.due_date >= start)
            .filter(AccountingAccount.due_date <= end)
            .scalar()
        )
        payables = (
            db.session.query(func.coalesce(func.sum(AccountingAccount.net_amount), 0))
            .filter(AccountingAccount.clinic_id == clinic_id)
            .filter(AccountingAccount.kind == "payable")
            .filter(AccountingAccount.status == "open")
            .filter(AccountingAccount.due_date >= start)
            .filter(AccountingAccount.due_date <= end)
            .scalar()
        )
        projections[label] = {
            "entradas": _quantize_currency(_ensure_decimal(receivables)),
            "saidas": _quantize_currency(_ensure_decimal(payables)),
            "saldo": _quantize_currency(_ensure_decimal(receivables) - _ensure_decimal(payables)),
        }

    return {
        "clinic_id": clinic_id,
        "month": month_start,
        "month_end": month_end,
        "realizado": {
            "entradas": _quantize_currency(entradas),
            "saidas": _quantize_currency(saidas),
            "saldo": _quantize_currency(entradas - saidas),
        },
        "projecoes": projections,
    }


def sync_receivable_from_nfse(document: FiscalDocument, commit: bool = True) -> AccountingAccount | None:
    """Create/update ContaReceber from an authorized NFS-e document."""

    if not document or document.status != FiscalDocumentStatus.AUTHORIZED:
        return None
    gross = _quantize_currency(_ensure_decimal(document.total_amount))
    if gross <= ZERO:
        return None
    clinic = document.clinic or Clinica.query.get(document.clinic_id)
    iss_rate = _normalize_percentage(getattr(clinic, "aliquota_iss", DEFAULT_ISS_RATE) if clinic else DEFAULT_ISS_RATE)
    pis_value = getattr(clinic, "aliquota_pis", None) if clinic else None
    cofins_value = getattr(clinic, "aliquota_cofins", None) if clinic else None
    pis_rate = _normalize_percentage(pis_value if pis_value is not None else ZERO)
    cofins_rate = _normalize_percentage(cofins_value if cofins_value is not None else ZERO)
    tax_total = _quantize_currency(gross * (iss_rate + pis_rate + cofins_rate))
    reference_dt = document.authorized_at or document.updated_at or document.created_at or utcnow()
    issue_date = reference_dt.date() if isinstance(reference_dt, datetime) else date.today()
    due_date = issue_date + timedelta(days=30)
    account = (
        AccountingAccount.query.filter_by(
            clinic_id=document.clinic_id,
            source_type="fiscal_document",
            source_id=document.id,
            kind="receivable",
        ).one_or_none()
    )
    if account is None:
        account = AccountingAccount(
            clinic_id=document.clinic_id,
            kind="receivable",
            source_type="fiscal_document",
            source_id=document.id,
        )
        db.session.add(account)
    account.status = account.status or "open"
    account.description = _prepare_description(
        f"NFS-e {document.nfse_number or document.number or document.id}",
        "NFS-e autorizada",
    )
    account.counterparty_name = document.tutor_name
    account.gross_amount = gross
    account.tax_amount = tax_total
    account.net_amount = _quantize_currency(gross - tax_total)
    account.issue_date = issue_date
    account.due_date = due_date
    account.source_reference = document.nfse_number or str(document.number or document.id)
    if commit:
        db.session.commit()
    return account


def register_account(
    clinic_id: int,
    kind: str,
    description: str,
    amount,
    due_date: date,
    *,
    counterparty_name: Optional[str] = None,
    issue_date: Optional[date] = None,
    source_type: Optional[str] = "manual",
    source_id: Optional[int] = None,
) -> AccountingAccount:
    kind = (kind or "").strip().lower()
    if kind not in {"receivable", "payable"}:
        raise ValueError("kind must be receivable or payable")
    gross = _quantize_currency(_ensure_decimal(amount))
    account = AccountingAccount(
        clinic_id=clinic_id,
        kind=kind,
        status="open",
        description=_prepare_description(description, "Conta"),
        counterparty_name=counterparty_name,
        gross_amount=gross,
        tax_amount=ZERO,
        net_amount=gross,
        issue_date=issue_date or date.today(),
        due_date=due_date,
        source_type=source_type,
        source_id=source_id,
    )
    db.session.add(account)
    db.session.commit()
    return account


def _parse_ofx_date(value: str) -> date:
    digits = re.sub(r"[^0-9]", "", value or "")
    return datetime.strptime(digits[:8], "%Y%m%d").date()


def parse_ofx_transactions(ofx_text: str) -> list[dict]:
    transactions = []
    for block in re.findall(r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|$)", ofx_text or "", flags=re.I | re.S):
        def _tag(name: str) -> str:
            match = re.search(rf"<{name}>([^<\r\n]+)", block, flags=re.I)
            return (match.group(1).strip() if match else "")

        amount = _ensure_decimal(_tag("TRNAMT"))
        posted_raw = _tag("DTPOSTED")
        if not posted_raw:
            continue
        transactions.append(
            {
                "posted_at": _parse_ofx_date(posted_raw),
                "amount": _quantize_currency(amount),
                "memo": _prepare_description(_tag("MEMO") or _tag("NAME"), "Lançamento bancário"),
                "fit_id": _tag("FITID") or None,
            }
        )
    return transactions


def import_bank_statement(clinic_id: int, content: str, file_type: str = "ofx") -> dict:
    """Import OFX/CNAB-like transactions and match by amount + date within +/- 2 days."""

    if (file_type or "ofx").lower() == "ofx":
        parsed = parse_ofx_transactions(content)
    else:
        parsed = []
        reader = csv.DictReader(io.StringIO(content), delimiter=";")
        for row in reader:
            amount = row.get("valor") or row.get("amount") or "0"
            posted = row.get("data") or row.get("posted_at")
            if posted:
                parsed.append(
                    {
                        "posted_at": datetime.strptime(posted[:10], "%Y-%m-%d").date(),
                        "amount": _quantize_currency(_ensure_decimal(amount.replace(",", "."))),
                        "memo": _prepare_description(row.get("descricao") or row.get("memo"), "CNAB"),
                        "fit_id": row.get("id") or row.get("fit_id"),
                    }
                )

    imported = 0
    matched = 0
    for item in parsed:
        tx = None
        if item.get("fit_id"):
            tx = BankStatementTransaction.query.filter_by(
                clinic_id=clinic_id,
                fit_id=item["fit_id"],
            ).one_or_none()
        if tx is None:
            tx = BankStatementTransaction(clinic_id=clinic_id, fit_id=item.get("fit_id"))
            db.session.add(tx)
            imported += 1
        tx.posted_at = item["posted_at"]
        tx.amount = item["amount"]
        tx.memo = item["memo"]

        kind = "receivable" if _ensure_decimal(tx.amount) > ZERO else "payable"
        absolute_amount = abs(_ensure_decimal(tx.amount))
        window_start = tx.posted_at - timedelta(days=2)
        window_end = tx.posted_at + timedelta(days=2)
        account = (
            AccountingAccount.query
            .filter(AccountingAccount.clinic_id == clinic_id)
            .filter(AccountingAccount.kind == kind)
            .filter(AccountingAccount.status == "open")
            .filter(AccountingAccount.due_date >= window_start)
            .filter(AccountingAccount.due_date <= window_end)
            .filter(AccountingAccount.net_amount == absolute_amount)
            .order_by(AccountingAccount.due_date.asc())
            .first()
        )
        if account:
            account.mark_paid(tx.posted_at, tx)
            tx.matched_account = account
            tx.match_confidence = Decimal("0.95")
            matched += 1
    db.session.commit()
    return {"imported": imported, "matched": matched, "total": len(parsed)}


def build_accounting_dashboard(clinic_id: int, month: Optional[date | datetime | str] = None) -> dict:
    month_start = _normalize_month(month)
    month_end = month_start + relativedelta(months=1)
    classify_transactions_for_month(clinic_id, month_start)
    taxes = calculate_clinic_taxes(clinic_id, month_start)
    revenue = _sum_categories(clinic_id, month_start, REVENUE_CATEGORIES)
    orders = (
        db.session.query(func.count(ClassifiedTransaction.id))
        .filter(ClassifiedTransaction.clinic_id == clinic_id)
        .filter(ClassifiedTransaction.month == month_start)
        .filter(ClassifiedTransaction.category.in_(list(REVENUE_CATEGORIES)))
        .scalar()
    ) or 0
    overdue = (
        db.session.query(func.coalesce(func.sum(AccountingAccount.net_amount), 0))
        .filter(AccountingAccount.clinic_id == clinic_id)
        .filter(AccountingAccount.kind == "receivable")
        .filter(AccountingAccount.status == "open")
        .filter(AccountingAccount.due_date < date.today())
        .scalar()
    )
    tax_total = _ensure_decimal(taxes.iss_total) + _ensure_decimal(taxes.das_total) + _ensure_decimal(taxes.retencoes_pj)
    top_services = (
        db.session.query(
            ClassifiedTransaction.subcategory,
            func.count(ClassifiedTransaction.id),
            func.coalesce(func.sum(ClassifiedTransaction.value), 0),
        )
        .filter(ClassifiedTransaction.clinic_id == clinic_id)
        .filter(ClassifiedTransaction.month == month_start)
        .filter(ClassifiedTransaction.category == "receita_servico")
        .group_by(ClassifiedTransaction.subcategory)
        .order_by(func.coalesce(func.sum(ClassifiedTransaction.value), 0).desc())
        .limit(10)
        .all()
    )
    return {
        "month": month_start,
        "faturamento_mes": _quantize_currency(revenue),
        "ticket_medio": _quantize_currency(revenue / Decimal(orders)) if orders else ZERO,
        "inadimplencia": _quantize_currency(_ensure_decimal(overdue)),
        "carga_tributaria_real": _quantize_factor(tax_total / revenue) if revenue > ZERO else ZERO,
        "top_servicos": [
            {"servico": name or "Serviço", "quantidade": count, "total": _quantize_currency(_ensure_decimal(total))}
            for name, count, total in top_services
        ],
    }


def build_veterinarian_revenue_report(clinic_id: int, month: Optional[date | datetime | str] = None) -> list[dict]:
    month_start = _normalize_month(month)
    start_dt, end_dt = _month_range(month_start)
    vet_id_column = getattr(Consulta, "created_by", None)
    if vet_id_column is None:
        return []
    vet_name = func.coalesce(User.name, "Veterinário")
    rows = (
        db.session.query(vet_id_column, vet_name, func.coalesce(func.sum(OrcamentoItem.valor), 0))
        .join(Consulta, Consulta.id == OrcamentoItem.consulta_id)
        .outerjoin(User, User.id == Consulta.created_by)
        .filter(OrcamentoItem.clinica_id == clinic_id)
        .filter(Consulta.created_at >= start_dt)
        .filter(Consulta.created_at < end_dt)
        .group_by(vet_id_column, vet_name)
        .order_by(func.coalesce(func.sum(OrcamentoItem.valor), 0).desc())
        .all()
    )
    return [
        {"veterinario_id": vet_id, "nome": name, "faturamento": _quantize_currency(_ensure_decimal(total))}
        for vet_id, name, total in rows
    ]


def _xlsx_escape(value) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _xlsx_cell(col_index: int, row_index: int, value) -> str:
    col = ""
    idx = col_index
    while idx:
        idx, rem = divmod(idx - 1, 26)
        col = chr(65 + rem) + col
    ref = f"{col}{row_index}"
    if isinstance(value, (int, float, Decimal)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{_xlsx_escape(value)}</t></is></c>'


def _minimal_xlsx(sheets: dict[str, list[list]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>""" + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1)) + "</Types>")
        zf.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>""")
        zf.writestr("xl/workbook.xml", """<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>""" + "".join(f'<sheet name="{_xlsx_escape(name[:31])}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(sheets, start=1)) + "</sheets></workbook>")
        zf.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">""" + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1)) + "</Relationships>")
        for i, rows in enumerate(sheets.values(), start=1):
            sheet_xml = ['<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
            for row_idx, row in enumerate(rows, start=1):
                sheet_xml.append(f'<row r="{row_idx}">')
                for col_idx, value in enumerate(row, start=1):
                    sheet_xml.append(_xlsx_cell(col_idx, row_idx, value))
                sheet_xml.append("</row>")
            sheet_xml.append("</sheetData></worksheet>")
            zf.writestr(f"xl/worksheets/sheet{i}.xml", "".join(sheet_xml))
    return buffer.getvalue()


def export_accountant_xlsx(clinic_id: int, month: Optional[date | datetime | str] = None) -> bytes:
    month_start = _normalize_month(month)
    dre = build_dre_report(clinic_id, month_start, "monthly")
    cash = build_cash_flow_report(clinic_id, month_start)
    dashboard = build_accounting_dashboard(clinic_id, month_start)
    vets = build_veterinarian_revenue_report(clinic_id, month_start)
    accounts = (
        AccountingAccount.query
        .filter(AccountingAccount.clinic_id == clinic_id)
        .filter(or_(AccountingAccount.issue_date >= month_start, AccountingAccount.due_date >= month_start))
        .filter(or_(AccountingAccount.issue_date < month_start + relativedelta(months=1), AccountingAccount.due_date < month_start + relativedelta(months=1)))
        .order_by(AccountingAccount.due_date.asc())
        .all()
    )
    sheets = {
        "Resumo": [
            ["Indicador", "Valor"],
            ["Faturamento mes", dashboard["faturamento_mes"]],
            ["Ticket medio", dashboard["ticket_medio"]],
            ["Inadimplencia", dashboard["inadimplencia"]],
            ["Carga tributaria real", dashboard["carga_tributaria_real"]],
        ],
        "DRE": [
            ["Mes", "Receita servicos", "Receita produtos", "Impostos", "Custos produtos", "Despesas fixas", "Resultado liquido"],
        ] + [
            [
                row["month"].isoformat(),
                row["receitas_servicos"],
                row["receitas_produtos"],
                row["impostos"],
                row["custos_produtos"],
                row["despesas_fixas"],
                row["resultado_liquido"],
            ]
            for row in dre["rows"]
        ],
        "Fluxo Caixa": [
            ["Tipo", "Entradas", "Saidas", "Saldo"],
            ["Realizado", cash["realizado"]["entradas"], cash["realizado"]["saidas"], cash["realizado"]["saldo"]],
        ] + [
            [f"Projecao {label} dias", values["entradas"], values["saidas"], values["saldo"]]
            for label, values in cash["projecoes"].items()
        ],
        "Contas": [
            ["Tipo", "Status", "Descricao", "Contraparte", "Vencimento", "Baixa", "Bruto", "Impostos", "Liquido", "Origem"],
        ] + [
            [
                account.kind,
                account.status,
                account.description,
                account.counterparty_name,
                account.due_date.isoformat() if account.due_date else "",
                account.paid_at.isoformat() if account.paid_at else "",
                account.gross_amount,
                account.tax_amount,
                account.net_amount,
                f"{account.source_type or ''}:{account.source_reference or account.source_id or ''}",
            ]
            for account in accounts
        ],
        "Top Servicos": [["Servico", "Quantidade", "Total"]] + [
            [item["servico"], item["quantidade"], item["total"]] for item in dashboard["top_servicos"]
        ],
        "Veterinarios": [["Veterinario", "Faturamento"]] + [
            [row["nome"], row["faturamento"]] for row in vets
        ],
    }
    return _minimal_xlsx(sheets)


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
    snapshot.gerado_em = utcnow()
    snapshot.refresh_totals()
    db.session.commit()

    classify_transactions_for_month(clinic_id, month_start)
    calculate_clinic_taxes(clinic_id, month_start)
    generate_clinic_notifications(clinic_id, month_start)
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
