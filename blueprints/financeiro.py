"""Contabilidade e financeiro da clínica — views do domínio.

Vários helpers de contabilidade/plantonistas ainda vivem no app.py e são
importados de lá (realocação prevista para fases futuras). ``_is_admin`` e
``classify_transactions_for_month`` são late-bound via módulo app porque
testes fazem monkeypatch desses nomes.
"""
import json
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Optional

from dateutil.relativedelta import relativedelta
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import joinedload, selectinload

from extensions import db
from forms import PJPaymentForm, PlantonistaEscalaForm
from models import (
    AccountingAccount,
    Animal,
    BlocoOrcamento,
    ClassifiedTransaction,
    ClinicFinancialSnapshot,
    ClinicNotification,
    ClinicTaxes,
    Clinica,
    Consulta,
    NfseIssue,
    NfseXml,
    Orcamento,
    PJPayment,
    PLANTONISTA_ESCALA_STATUS_CHOICES,
    PlantaoModelo,
    PlantonistaEscala,
    Veterinario,
    clinica_has_column,
    get_clinica_field,
)
from security.crypto import MissingMasterKeyError, decrypt_text_for_clinic, encrypt_text
from services.finance import (
    build_accounting_dashboard,
    build_cash_flow_report,
    build_dre_report,
    build_veterinarian_revenue_report,
    export_accountant_xlsx,
    import_bank_statement,
    register_account,
)
from services.fiscal.nfse_service import NFSE_NACIONAL_MUNICIPIO_IBGE_BY_KEY
from services.nfse_queue import (
    ensure_nfse_issue_for_consulta,
    get_nfse_cancel_rules,
    process_nfse_issue,
    process_nfse_queue,
    queue_nfse_issue,
    request_nfse_cancel,
    request_nfse_substitution,
    should_emit_async,
    validate_nfse_cancel_request,
)
from services.nfse_service import _normalize_municipio
from time_utils import utcnow

from app import (
    ACCOUNTING_BUDGET_STATUS_SUMMARY,
    ORCAMENTO_PAYMENT_STATUS_LABELS,
    PLANTONISTA_STATUS_STYLES,
    _accounting_accessible_clinics,
    _apply_modelo_to_form,
    _build_modelo_from_form,
    _build_nfse_emissor_payload,
    _build_nfse_orcamento_payload,
    _compute_plantao_horas,
    _configure_modelo_choices,
    _configure_pj_payment_form,
    _decimal_json,
    _delete_pj_payment_classification,
    _describe_pj_payments_schema_error,
    _describe_plantonista_schema_error,
    _ensure_accounting_access,
    _ensure_clinic_notifications_table,
    _format_month_parameter,
    _get_primary_payment_plantao,
    _load_plantao_modelos,
    _nfse_betha_status,
    _nfse_certificate_status,
    _nfse_field_labels,
    _nfse_missing_fields,
    _nfse_required_fields_by_municipio,
    _normalize_payment_status,
    _parse_month_parameter,
    _pj_payments_schema_issue,
    _plantonista_schema_issue,
    _populate_plantonista_form_choices,
    _prefill_plantao_fields_on_form,
    _select_accounting_clinic,
    _selected_accounting_context,
    _serialize_plantao_modelo,
    _sync_payment_plantao_link,
    _sync_pj_payment_classification,
)

bp = Blueprint("financeiro_routes", __name__)


def get_blueprint():
    return bp


def _is_admin():
    import app as app_module

    return app_module._is_admin()


def classify_transactions_for_month(*args, **kwargs):
    import app as app_module

    return app_module.classify_transactions_for_month(*args, **kwargs)


@bp.route("/contabilidade", methods=["GET"])
@login_required
def contabilidade_home():
    _ensure_accounting_access()
    clinics, accessible_ids = _accounting_accessible_clinics()

    requested_id = request.args.get('clinica_id', type=int)
    selected_clinic = _select_accounting_clinic(
        clinics,
        accessible_ids,
        requested_clinic_id=requested_id,
    )

    current_month = date.today().replace(day=1)
    notifications = []
    if selected_clinic and _ensure_clinic_notifications_table():
        notifications = (
            ClinicNotification.query
            .filter_by(
                clinic_id=selected_clinic.id,
                month=current_month,
                resolved=False,
            )
            .order_by(ClinicNotification.created_at.desc())
            .all()
        )

    return render_template(
        'contabilidade/index.html',
        clinics=clinics,
        selected_clinic=selected_clinic,
        notifications=notifications,
        current_month=current_month,
    )


@bp.route("/contabilidade/financeiro", methods=["GET"])
@login_required
def contabilidade_financeiro():
    _ensure_accounting_access()
    clinics, accessible_ids = _accounting_accessible_clinics()

    requested_clinic_id = request.args.get('clinica_id', type=int)
    selected_clinic = _select_accounting_clinic(
        clinics,
        accessible_ids,
        requested_clinic_id=requested_clinic_id,
    )
    selected_clinic_id = selected_clinic.id if selected_clinic else None

    pj_schema_issue = _pj_payments_schema_issue()
    pj_payments_available = pj_schema_issue is None
    if pj_schema_issue and selected_clinic_id:
        flash(pj_schema_issue[1], 'warning')

    month_reference = date.today().replace(day=1)
    months = [month_reference - relativedelta(months=offset) for offset in range(11, -1, -1)]
    month_names = [
        'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
        'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'
    ]

    def _format_month_label(month_value):
        return f"{month_names[month_value.month - 1]}/{month_value.year}"

    revenues_labels = [_format_month_label(month) for month in months]
    revenues_values: list[float] = []
    pj_payments_values: list[float] = []
    pj_plantonista_values: list[float] = []
    pj_outros_values: list[float] = []
    fator_r_values: list[float] = []
    projection_values: list[float] = []

    monthly_revenues: dict[date, Decimal] = {}
    monthly_pj_totals: dict[date, Decimal] = {}
    monthly_pj_plantonistas: dict[date, Decimal] = {}
    monthly_pj_outros: dict[date, Decimal] = {}
    monthly_taxes: dict[date, ClinicTaxes] = {}

    if selected_clinic_id:
        snapshots = (
            ClinicFinancialSnapshot.query
            .filter(ClinicFinancialSnapshot.clinic_id == selected_clinic_id)
            .filter(ClinicFinancialSnapshot.month.in_(months))
            .all()
        )
        monthly_revenues = {
            snapshot.month: Decimal(snapshot.total_receitas_gerais or 0)
            for snapshot in snapshots
        }

        pj_totals = (
            db.session.query(
                ClassifiedTransaction.month,
                ClassifiedTransaction.subcategory,
                func.coalesce(func.sum(ClassifiedTransaction.value), 0),
            )
            .filter(ClassifiedTransaction.clinic_id == selected_clinic_id)
            .filter(ClassifiedTransaction.month.in_(months))
            .filter(ClassifiedTransaction.category == 'pagamento_pj')
            .group_by(ClassifiedTransaction.month, ClassifiedTransaction.subcategory)
            .all()
        )
        totals_map: dict[date, Decimal] = defaultdict(lambda: Decimal('0'))
        plantonista_map: dict[date, Decimal] = defaultdict(lambda: Decimal('0'))
        outros_map: dict[date, Decimal] = defaultdict(lambda: Decimal('0'))
        for month_value, subcategory, total in pj_totals:
            total_decimal = Decimal(total or 0)
            totals_map[month_value] += total_decimal
            if (subcategory or '').lower() == 'plantonista':
                plantonista_map[month_value] += total_decimal
            else:
                outros_map[month_value] += total_decimal
        monthly_pj_totals = dict(totals_map)
        monthly_pj_plantonistas = dict(plantonista_map)
        monthly_pj_outros = dict(outros_map)

        taxes_records = (
            ClinicTaxes.query
            .filter(ClinicTaxes.clinic_id == selected_clinic_id)
            .filter(ClinicTaxes.month.in_(months))
            .all()
        )
        monthly_taxes = {record.month: record for record in taxes_records}

    for month in months:
        revenue_total = monthly_revenues.get(month, Decimal('0'))
        revenues_values.append(float(revenue_total))

        pj_total = monthly_pj_totals.get(month, Decimal('0'))
        pj_payments_values.append(float(pj_total))
        pj_plantonista_values.append(float(monthly_pj_plantonistas.get(month, Decimal('0'))))
        pj_outros_values.append(float(monthly_pj_outros.get(month, Decimal('0'))))

        taxes_record = monthly_taxes.get(month)
        fator_r = Decimal('0')
        projection = Decimal('0')
        if taxes_record:
            fator_r = Decimal(taxes_record.fator_r or 0)
            projection = Decimal(taxes_record.projecao_anual or 0)
        fator_r_values.append(float(fator_r))
        projection_values.append(float(projection))

    current_month = months[-1]
    resumo_mes_label = _format_month_label(current_month)
    resumo_faturamento = monthly_revenues.get(current_month, Decimal('0'))
    resumo_pj_custos = monthly_pj_totals.get(current_month, Decimal('0'))
    resumo_pj_plantonistas = monthly_pj_plantonistas.get(current_month, Decimal('0'))
    resumo_pj_outros = monthly_pj_outros.get(current_month, Decimal('0'))
    resumo_projecao = Decimal('0')
    resumo_impostos = Decimal('0')

    plantonista_sem_nf = 0
    plantonista_total_horas = Decimal('0')
    plantonista_escalas = 0
    plantonista_media = Decimal('0')
    plantonista_custo_hora = Decimal('0')

    taxes_for_current = monthly_taxes.get(current_month)
    if taxes_for_current:
        resumo_projecao = Decimal(taxes_for_current.projecao_anual or 0)
        resumo_impostos = (
            Decimal(taxes_for_current.iss_total or 0)
            + Decimal(taxes_for_current.das_total or 0)
            + Decimal(taxes_for_current.retencoes_pj or 0)
        )

    if selected_clinic_id and pj_payments_available:
        month_end = current_month + relativedelta(months=1)
        plantonista_records = (
            PJPayment.query
            .filter(PJPayment.clinic_id == selected_clinic_id)
            .filter(PJPayment.data_servico >= current_month)
            .filter(PJPayment.data_servico < month_end)
            .filter(func.lower(func.coalesce(PJPayment.tipo_prestador, '')) == 'plantonista')
            .all()
        )
        plantonista_escalas = len(plantonista_records)
        for payment in plantonista_records:
            if not (payment.nota_fiscal_numero or '').strip():
                plantonista_sem_nf += 1
            if payment.plantao_horas:
                plantonista_total_horas += Decimal(str(payment.plantao_horas))
        if plantonista_escalas:
            plantonista_media = resumo_pj_plantonistas / plantonista_escalas
        if plantonista_total_horas > 0:
            plantonista_custo_hora = resumo_pj_plantonistas / plantonista_total_horas

    has_chart_data = any(
        value != 0
        for value in (
            revenues_values
            + pj_payments_values
            + pj_plantonista_values
            + pj_outros_values
            + fator_r_values
            + projection_values
        )
    )
    dashboard_metrics = (
        build_accounting_dashboard(selected_clinic_id, current_month)
        if selected_clinic_id
        else None
    )
    vet_report = (
        build_veterinarian_revenue_report(selected_clinic_id, current_month)
        if selected_clinic_id
        else []
    )

    return render_template(
        'contabilidade/financeiro.html',
        clinics=clinics,
        selected_clinic_id=selected_clinic_id,
        selected_clinic=selected_clinic,
        revenues_labels=revenues_labels,
        revenues_values=revenues_values,
        pj_payments_values=pj_payments_values,
        pj_plantonista_values=pj_plantonista_values,
        pj_outros_values=pj_outros_values,
        fator_r_values=fator_r_values,
        projection_values=projection_values,
        resumo_mes_label=resumo_mes_label,
        resumo_faturamento=resumo_faturamento,
        resumo_pj_custos=resumo_pj_custos,
        resumo_pj_plantonistas=resumo_pj_plantonistas,
        resumo_pj_outros=resumo_pj_outros,
        resumo_impostos=resumo_impostos,
        resumo_projecao=resumo_projecao,
        plantonista_sem_nf=plantonista_sem_nf,
        plantonista_total_horas=plantonista_total_horas,
        plantonista_escalas=plantonista_escalas,
        plantonista_media=plantonista_media,
        plantonista_custo_hora=plantonista_custo_hora,
        has_chart_data=has_chart_data,
        dashboard_metrics=dashboard_metrics,
        vet_report=vet_report,
    )


@bp.route("/contabilidade/dre", methods=["GET"])
@login_required
def contabilidade_dre():
    _ensure_accounting_access()
    clinics, selected_clinic, selected_month = _selected_accounting_context()
    period = (request.args.get('periodo') or 'monthly').lower()
    report = build_dre_report(selected_clinic.id, selected_month, period) if selected_clinic else None
    if request.accept_mimetypes.best == 'application/json' or request.args.get('format') == 'json':
        return jsonify(_decimal_json(report or {}))
    return render_template(
        'contabilidade/dre.html',
        clinics=clinics,
        selected_clinic=selected_clinic,
        selected_month=selected_month,
        selected_period=period,
        report=report,
    )


@bp.route("/contabilidade/fluxo-caixa", methods=["GET"])
@login_required
def contabilidade_fluxo_caixa():
    _ensure_accounting_access()
    clinics, selected_clinic, selected_month = _selected_accounting_context()
    report = build_cash_flow_report(selected_clinic.id, selected_month) if selected_clinic else None
    if request.accept_mimetypes.best == 'application/json' or request.args.get('format') == 'json':
        return jsonify(_decimal_json(report or {}))
    return render_template(
        'contabilidade/fluxo_caixa.html',
        clinics=clinics,
        selected_clinic=selected_clinic,
        selected_month=selected_month,
        report=report,
    )


@bp.route("/contabilidade/contas", methods=["GET", "POST"])
@login_required
def contabilidade_contas():
    _ensure_accounting_access()
    clinics, selected_clinic, selected_month = _selected_accounting_context()
    if not selected_clinic:
        return render_template('contabilidade/contas.html', clinics=clinics, selected_clinic=None, selected_month=selected_month, accounts=[])

    if request.method == 'POST':
        due_date_raw = request.form.get('due_date') or request.form.get('vencimento')
        try:
            due_date = datetime.strptime(due_date_raw, '%Y-%m-%d').date()
            register_account(
                selected_clinic.id,
                request.form.get('kind') or request.form.get('tipo') or 'payable',
                request.form.get('description') or request.form.get('descricao') or 'Conta manual',
                request.form.get('amount') or request.form.get('valor') or '0',
                due_date,
                counterparty_name=request.form.get('counterparty_name') or request.form.get('contraparte'),
            )
            flash('Conta registrada com sucesso.', 'success')
        except Exception as exc:
            db.session.rollback()
            current_app.logger.warning('Falha ao registrar conta: %s', exc, exc_info=exc)
            flash('Nao foi possivel registrar a conta. Confira os campos.', 'danger')
        return redirect(url_for('contabilidade_contas', clinica_id=selected_clinic.id, mes=selected_month.strftime('%Y-%m')))

    month_end = selected_month + relativedelta(months=1)
    accounts = (
        AccountingAccount.query
        .filter(AccountingAccount.clinic_id == selected_clinic.id)
        .filter(or_(AccountingAccount.due_date.is_(None), and_(AccountingAccount.due_date >= selected_month, AccountingAccount.due_date < month_end)))
        .order_by(AccountingAccount.status.asc(), AccountingAccount.due_date.asc(), AccountingAccount.id.desc())
        .all()
    )
    if request.args.get('format') == 'json':
        payload = [
            {
                'id': account.id,
                'kind': account.kind,
                'status': account.status,
                'description': account.description,
                'due_date': account.due_date,
                'paid_at': account.paid_at,
                'net_amount': account.net_amount,
                'source_reference': account.source_reference,
            }
            for account in accounts
        ]
        return jsonify(_decimal_json(payload))
    return render_template(
        'contabilidade/contas.html',
        clinics=clinics,
        selected_clinic=selected_clinic,
        selected_month=selected_month,
        accounts=accounts,
    )


@bp.route("/contabilidade/conciliacao/importar", methods=["POST"])
@login_required
def contabilidade_conciliacao_importar():
    _ensure_accounting_access()
    clinics, selected_clinic, selected_month = _selected_accounting_context()
    if not selected_clinic:
        abort(400)
    uploaded = request.files.get('arquivo') or request.files.get('file')
    if not uploaded:
        flash('Envie um arquivo OFX ou CNAB.', 'warning')
        return redirect(url_for('contabilidade_contas', clinica_id=selected_clinic.id, mes=selected_month.strftime('%Y-%m')))
    content = uploaded.read().decode('utf-8', errors='ignore')
    result = import_bank_statement(selected_clinic.id, content, file_type=(uploaded.filename or '').rsplit('.', 1)[-1])
    flash(f"Extrato importado: {result['total']} lancamento(s), {result['matched']} conciliado(s).", 'success')
    return redirect(url_for('contabilidade_contas', clinica_id=selected_clinic.id, mes=selected_month.strftime('%Y-%m')))


@bp.route("/contabilidade/exportar/xlsx", methods=["GET"])
@login_required
def contabilidade_exportar_xlsx():
    _ensure_accounting_access()
    _clinics, selected_clinic, selected_month = _selected_accounting_context()
    if not selected_clinic:
        abort(400)
    content = export_accountant_xlsx(selected_clinic.id, selected_month)
    response = make_response(content)
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    filename = f"relatorio-contabil-{selected_clinic.id}-{selected_month:%Y-%m}.xlsx"
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@bp.route("/api/contabilidade/dashboard", methods=["GET"])
@login_required
def api_contabilidade_dashboard():
    _ensure_accounting_access()
    _clinics, selected_clinic, selected_month = _selected_accounting_context()
    if not selected_clinic:
        return jsonify({})
    return jsonify(_decimal_json(build_accounting_dashboard(selected_clinic.id, selected_month)))


@bp.route("/api/contabilidade/veterinarios", methods=["GET"])
@login_required
def api_contabilidade_veterinarios():
    _ensure_accounting_access()
    _clinics, selected_clinic, selected_month = _selected_accounting_context()
    if not selected_clinic:
        return jsonify([])
    return jsonify(_decimal_json(build_veterinarian_revenue_report(selected_clinic.id, selected_month)))


@bp.route("/contabilidade/pagamentos", methods=["GET"])
@login_required
def contabilidade_pagamentos():
    _ensure_accounting_access()
    clinics, accessible_ids = _accounting_accessible_clinics()

    requested_clinic_id = request.args.get('clinica_id', type=int)
    selected_clinic = _select_accounting_clinic(
        clinics,
        accessible_ids,
        requested_clinic_id=requested_clinic_id,
    )
    selected_clinic_id = selected_clinic.id if selected_clinic else None

    selected_month = _parse_month_parameter(request.args.get('mes'))
    start_date = selected_month
    end_date = selected_month + relativedelta(months=1)
    context_month_value = selected_month.strftime('%Y-%m')

    requested_month = (request.args.get('mes') or '')[:7]
    requested_clinic_id = request.args.get('clinica_id', type=int)
    raw_view_param = (request.args.get('aba') or request.args.get('view') or '').strip().lower()
    allowed_views = {'geral', 'plantonistas'}
    selected_view = raw_view_param if raw_view_param in allowed_views else 'geral'
    needs_redirect = False

    if selected_clinic_id:
        if requested_clinic_id != selected_clinic_id:
            needs_redirect = True
    elif 'clinica_id' in request.args:
        needs_redirect = True

    if requested_month != context_month_value:
        needs_redirect = True

    canonical_params = {'mes': context_month_value}
    if selected_clinic_id:
        canonical_params['clinica_id'] = selected_clinic_id
    if selected_view != 'geral':
        canonical_params['aba'] = selected_view

    if raw_view_param and raw_view_param not in allowed_views:
        needs_redirect = True
    if 'view' in request.args:
        needs_redirect = True

    if needs_redirect:
        return redirect(url_for('contabilidade_pagamentos', **canonical_params))

    payments: list[PJPayment] = []
    payments_error = None
    pj_schema_issue = _pj_payments_schema_issue()
    pj_payments_available = pj_schema_issue is None
    if pj_schema_issue:
        payments_error = pj_schema_issue[1]
    budget_entries: list[dict] = []
    budget_totals = {
        status: Decimal('0.00') for status in ACCOUNTING_BUDGET_STATUS_SUMMARY
    }

    start_datetime = datetime.combine(start_date, time.min)
    end_datetime = datetime.combine(end_date, time.min)

    plantonista_escalas: list[PlantonistaEscala] = []
    plantonista_totals = {
        'horas_previstas': Decimal('0.00'),
        'custo_previsto': Decimal('0.00'),
        'custo_pago': Decimal('0.00'),
    }
    plantonista_medicos: list[dict] = []
    plantao_modelos_serialized: list[dict] = []
    plantonista_calendar: list[dict] = []
    plantonista_calendar_weeks: list[list[Optional[dict]]] = []
    plantonista_daily_map: dict[str, dict] = {}
    plantonista_error: Optional[str] = None

    def _coerce_decimal(value):
        if value is None:
            return Decimal('0.00')
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal('0.00')

    def _normalize_budget_status(raw_status: Optional[str]) -> str:
        normalized = (raw_status or '').strip().lower()
        if normalized in {'', 'draft', 'not_generated', 'no_link', 'sem_link'}:
            return 'sem_link'
        if normalized in {'paid', 'success', 'approved', 'completed'}:
            return 'pago'
        if normalized in {'failed', 'canceled', 'cancelled', 'rejected', 'expired'}:
            return 'cancelado'
        return 'pendente'

    def _humanize_payment_status(raw_status: Optional[str]) -> str:
        normalized = _normalize_payment_status(raw_status)
        if not normalized or normalized == 'draft':
            return 'Sem link'
        return ORCAMENTO_PAYMENT_STATUS_LABELS.get(
            normalized,
            normalized.replace('_', ' ').title(),
        )

    badge_by_status = {
        'sem_link': 'bg-info text-dark',
        'pendente': 'bg-warning text-dark',
        'pago': 'bg-success',
        'cancelado': 'bg-secondary',
    }

    def _sync_metadata(status_code: str):
        if status_code == 'pago':
            return 'Sincronizado', 'fas fa-check-circle', 'success'
        if status_code == 'cancelado':
            return 'Cancelado', 'fas fa-ban', 'secondary'
        if status_code == 'sem_link':
            return 'Sem link gerado', 'fas fa-unlink', 'info'
        return 'Aguardando pagamento', 'fas fa-clock', 'warning'

    def _build_budget_entry(*, entry_type: str, title: str, total, raw_status: Optional[str],
                            reference_date: datetime, type_label: str,
                            context_label: Optional[str], source_url: Optional[str],
                            payment_entry_url: Optional[str]):
        status_key = _normalize_budget_status(raw_status)
        if status_key not in budget_totals:
            status_key = 'pendente'
        total_decimal = _coerce_decimal(total)
        budget_totals[status_key] += total_decimal
        sync_label, sync_icon, sync_color = _sync_metadata(status_key)
        subtitle_parts = [type_label]
        if context_label:
            subtitle_parts.append(context_label)
        subtitle_parts.append(f"Referência: {reference_date.strftime('%d/%m/%Y')}")
        return {
            'type': entry_type,
            'title': title,
            'total': total_decimal,
            'status_label': _humanize_payment_status(raw_status),
            'badge_class': badge_by_status.get(status_key, 'bg-secondary'),
            'reference_date': reference_date,
            'subtitle': ' • '.join(subtitle_parts),
            'sync_label': sync_label,
            'sync_icon': sync_icon,
            'sync_color': sync_color,
            'source_url': source_url,
            'payment_entry_url': payment_entry_url,
        }
    if selected_clinic_id and pj_payments_available:
        try:
            classify_transactions_for_month(selected_clinic_id, start_date)
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "Falha ao classificar transações para a clínica %s no mês %s",
                selected_clinic_id,
                start_date,
            )
        try:
            payments = (
                PJPayment.query.filter(PJPayment.clinic_id == selected_clinic_id)
                .filter(PJPayment.data_servico >= start_date)
                .filter(PJPayment.data_servico < end_date)
                .order_by(PJPayment.data_servico.desc(), PJPayment.id.desc())
                .all()
            )
        except ProgrammingError as exc:
            db.session.rollback()
            schema_issue = _describe_pj_payments_schema_error(exc)
            if schema_issue:
                log_message, user_message = schema_issue
                current_app.logger.warning(log_message, exc_info=exc)
                payments_error = user_message
            else:
                raise

        orcamentos_query = (
            Orcamento.query.options(
                joinedload(Orcamento.consulta).joinedload(Consulta.animal)
            )
            .filter(Orcamento.clinica_id == selected_clinic_id)
            .filter(
                or_(
                    and_(
                        Orcamento.paid_at.isnot(None),
                        Orcamento.paid_at >= start_datetime,
                        Orcamento.paid_at < end_datetime,
                    ),
                    and_(
                        Orcamento.paid_at.is_(None),
                        Orcamento.created_at >= start_datetime,
                        Orcamento.created_at < end_datetime,
                    ),
                )
            )
        )

        bloco_query = (
            BlocoOrcamento.query.options(
                joinedload(BlocoOrcamento.animal),
                joinedload(BlocoOrcamento.clinica),
            )
            .filter(BlocoOrcamento.clinica_id == selected_clinic_id)
            .filter(BlocoOrcamento.data_criacao >= start_datetime)
            .filter(BlocoOrcamento.data_criacao < end_datetime)
        )

        for orcamento in orcamentos_query.all():
            reference_date = orcamento.paid_at or orcamento.created_at or start_datetime
            animal_name = None
            if orcamento.consulta and orcamento.consulta.animal:
                animal_name = orcamento.consulta.animal.name
            payment_entry_url = None
            if orcamento.consulta_id:
                payment_entry_url = url_for('pagar_consulta_orcamento', consulta_id=orcamento.consulta_id)
            if orcamento.consulta and orcamento.consulta.animal_id:
                source_url = (
                    url_for(
                        'consulta_direct',
                        animal_id=orcamento.consulta.animal_id,
                        c=orcamento.consulta.id,
                    )
                    + '#orcamento'
                )
            else:
                source_url = url_for('editar_orcamento', orcamento_id=orcamento.id)
            budget_entries.append(
                _build_budget_entry(
                    entry_type='orcamento',
                    title=orcamento.descricao or f'Orçamento #{orcamento.id}',
                    total=orcamento.total,
                    raw_status=orcamento.payment_status,
                    reference_date=reference_date,
                    type_label='Orçamento',
                    context_label=animal_name,
                    source_url=source_url,
                    payment_entry_url=payment_entry_url,
                )
            )

        for bloco in bloco_query.all():
            reference_date = bloco.data_criacao or start_datetime
            animal_name = bloco.animal.name if bloco.animal else None
            clinic_name = bloco.clinica.nome if getattr(bloco, 'clinica', None) else None
            budget_entries.append(
                _build_budget_entry(
                    entry_type='bloco',
                    title=(
                        f"{animal_name} (Bloco #{bloco.id})"
                        if animal_name
                        else f"Bloco #{bloco.id}"
                    ),
                    total=bloco.total_liquido,
                    raw_status=bloco.payment_status,
                    reference_date=reference_date,
                    type_label='Bloco',
                    context_label=clinic_name,
                    source_url=url_for('editar_bloco_orcamento', bloco_id=bloco.id),
                    payment_entry_url=url_for('pagar_orcamento', bloco_id=bloco.id),
                )
            )

        budget_entries.sort(key=lambda entry: entry['reference_date'], reverse=True)

    if selected_view == 'plantonistas' and selected_clinic_id:
        schema_issue = _plantonista_schema_issue()
        if schema_issue:
            plantonista_error = schema_issue[1]
        else:
            try:
                plantonista_escalas = (
                    PlantonistaEscala.query.filter(
                        PlantonistaEscala.clinic_id == selected_clinic_id,
                        PlantonistaEscala.inicio >= start_datetime,
                        PlantonistaEscala.inicio < end_datetime,
                    )
                    .options(
                        selectinload(PlantonistaEscala.pj_payment),
                        selectinload(PlantonistaEscala.medico).joinedload(Veterinario.user),
                    )
                    .order_by(PlantonistaEscala.inicio.asc())
                    .all()
                )
            except ProgrammingError as exc:
                db.session.rollback()
                described = _describe_plantonista_schema_error(exc)
                if described:
                    current_app.logger.warning(described[0], exc_info=exc)
                    plantonista_error = described[1]
                else:
                    raise

        unique_medicos: dict[str, dict] = {}
        for escala in plantonista_escalas:
            plantonista_totals['horas_previstas'] += escala.horas_previstas or Decimal('0.00')
            plantonista_totals['custo_previsto'] += escala.valor_previsto or Decimal('0.00')
            plantonista_totals['custo_pago'] += escala.valor_pago or Decimal('0.00')
            if escala.medico_id and escala.medico_nome:
                medico_entry = unique_medicos.setdefault(
                    str(escala.medico_id),
                    {
                        'id': escala.medico_id,
                        'nome': escala.medico_nome,
                        'is_pj': False,
                        'clinicas': set(),
                        'ocupado_nas_datas': set(),
                        'nf_pendente': False,
                    },
                )
                medico_entry['nome'] = escala.medico_nome
                medico_entry['is_pj'] = medico_entry['is_pj'] or bool(escala.medico_cnpj)
                medico_entry['clinicas'].add(escala.clinic_id)
                if escala.inicio:
                    medico_entry['ocupado_nas_datas'].add(escala.inicio.date())
                if not getattr(escala, 'nota_fiscal_recebida', False) or not getattr(escala, 'retencao_validada', False):
                    medico_entry['nf_pendente'] = True

        if unique_medicos:
            try:
                medicos_db = (
                    Veterinario.query.options(selectinload(Veterinario.clinicas))
                    .filter(Veterinario.id.in_([int(mid) for mid in unique_medicos.keys()]))
                    .all()
                )
                for medico in medicos_db:
                    if medico and str(medico.id) in unique_medicos:
                        entry = unique_medicos[str(medico.id)]
                        entry['clinicas'] = set(entry.get('clinicas', set()) or [])
                        for clinica in getattr(medico, 'clinicas', []) or []:
                            entry['clinicas'].add(clinica.id)
            except Exception:
                current_app.logger.exception('Falha ao enriquecer dados dos médicos de plantão')

        plantonista_medicos = sorted(
            [
                {
                    'id': int(entry['id']),
                    'nome': entry['nome'],
                    'is_pj': entry.get('is_pj', False),
                    'clinicas_total': len(entry.get('clinicas', set()) or []),
                    'ocupado_nas_datas': sorted(
                        day.isoformat() if isinstance(day, date) else str(day)
                        for day in entry.get('ocupado_nas_datas', set())
                    ),
                    'nf_pendente': entry.get('nf_pendente', False),
                }
                for entry in unique_medicos.values()
            ],
            key=lambda item: item['nome'].lower(),
        )

        day_cursor = start_date
        now = utcnow()
        while day_cursor < end_date:
            day_start_dt = datetime.combine(day_cursor, time.min)
            day_end_dt = datetime.combine(day_cursor + timedelta(days=1), time.min)

            day_escalas = [
                escala
                for escala in plantonista_escalas
                if escala.inicio < day_end_dt and escala.fim > day_start_dt
            ]

            status_counts: dict[str, int] = defaultdict(int)
            horas_previstas = Decimal('0.00')
            valor_previsto_total = Decimal('0.00')
            medicos = set()
            atrasos = 0
            overdue_unpaid = 0
            daily_slots: list[dict] = []

            def _slot_status_for_escala(escala: PlantonistaEscala) -> tuple[str, str]:
                pago = escala.pj_payment and escala.pj_payment.status == 'pago'
                is_past = escala.fim < now
                if pago:
                    return 'pago', 'Pago'
                if is_past:
                    return 'vencido', 'Não pago (vencido)'
                return 'pendente', 'Agendado / pendente'

            for escala in day_escalas:
                status = (escala.status or 'agendado').strip().lower()
                status_counts[status] += 1
                horas_previstas += escala.horas_previstas or Decimal('0.00')
                valor_previsto_total += escala.valor_previsto or Decimal('0.00')
                if escala.medico_nome:
                    medicos.add(escala.medico_nome)
                if getattr(escala, 'atrasado', False):
                    atrasos += 1
                slot_status, slot_status_label = _slot_status_for_escala(escala)
                if slot_status == 'vencido':
                    overdue_unpaid += 1
                daily_slots.append(
                    {
                        'id': escala.id,
                        'turno': escala.turno or 'Plantão',
                        'inicio': escala.inicio,
                        'fim': escala.fim,
                        'medico': escala.medico_nome,
                        'status': slot_status,
                        'status_label': slot_status_label,
                        'valor_previsto': float(escala.valor_previsto or Decimal('0.00')),
                        'pago': slot_status == 'pago',
                    }
                )

            total_escalas = len(day_escalas)
            badge_label = 'Livre'
            badge_class = 'badge bg-light text-muted'
            if total_escalas:
                if atrasos:
                    badge_label = 'Pendência'
                    badge_class = 'badge bg-warning text-dark'
                elif status_counts.get('realizado'):
                    badge_label = 'Concluído'
                    badge_class = 'badge bg-success'
                elif status_counts.get('confirmado'):
                    badge_label = 'Confirmado'
                    badge_class = 'badge bg-primary'
                else:
                    badge_label = 'Agendado'
                    badge_class = 'badge bg-info text-dark'

            if not daily_slots:
                daily_slots.append(
                    {
                        'id': None,
                        'turno': 'Livre',
                        'inicio': day_start_dt,
                        'fim': day_end_dt,
                        'medico': None,
                        'status': 'livre',
                        'status_label': 'Dia livre',
                        'valor_previsto': 0.0,
                        'pago': False,
                    }
                )

            plantonista_calendar.append(
                {
                    'date': day_cursor,
                    'total_escalas': total_escalas,
                    'status_counts': dict(status_counts),
                    'horas': horas_previstas,
                    'valor_previsto': valor_previsto_total,
                    'badge_label': badge_label,
                    'badge_class': badge_class,
                    'atrasos': atrasos,
                    'medicos': sorted(medicos),
                }
            )

            plantonista_daily_map[day_cursor.isoformat()] = {
                'date': day_cursor,
                'overdue_unpaid': overdue_unpaid,
                'slots': daily_slots,
            }

            day_cursor += timedelta(days=1)

        current_week: list[Optional[dict]] = []
        for day_info in plantonista_calendar:
            if not current_week and day_info['date'].weekday() != 0:
                current_week.extend([None] * day_info['date'].weekday())
            current_week.append(day_info)
            if len(current_week) == 7:
                plantonista_calendar_weeks.append(current_week)
                current_week = []

        if current_week:
            while len(current_week) < 7:
                current_week.append(None)
            plantonista_calendar_weeks.append(current_week)

    if selected_view == 'plantonistas':
        modelo_clinic_ids = [selected_clinic_id] if selected_clinic_id else []
        plantao_modelos_serialized = [
            _serialize_plantao_modelo(modelo)
            for modelo in _load_plantao_modelos(modelo_clinic_ids)
        ]

    total_pago = sum((payment.valor or Decimal('0.00')) for payment in payments if payment.status == 'pago')
    total_pendente = sum((payment.valor or Decimal('0.00')) for payment in payments if payment.status == 'pendente')

    return render_template(
        'contabilidade/pagamentos.html',
        clinics=clinics,
        payments=payments,
        payments_error=payments_error,
        selected_clinic=selected_clinic,
        selected_clinic_id=selected_clinic_id,
        selected_month=selected_month,
        month_value=context_month_value,
        prev_month_value=(selected_month - relativedelta(months=1)).strftime('%Y-%m'),
        next_month_value=(selected_month + relativedelta(months=1)).strftime('%Y-%m'),
        total_pago=total_pago,
        total_pendente=total_pendente,
        budget_entries=budget_entries,
        budget_totals=budget_totals,
        budget_status_summary=ACCOUNTING_BUDGET_STATUS_SUMMARY,
        selected_view=selected_view,
        plantonista_escalas=plantonista_escalas,
        plantonista_totals=plantonista_totals,
        plantonista_medicos=plantonista_medicos,
        plantao_modelos_serialized=plantao_modelos_serialized,
        plantonista_calendar=plantonista_calendar,
        plantonista_calendar_weeks=plantonista_calendar_weeks,
        plantonista_daily_map=plantonista_daily_map,
        plantonista_status_labels=dict(PLANTONISTA_ESCALA_STATUS_CHOICES),
        plantonista_status_styles=PLANTONISTA_STATUS_STYLES,
        plantonista_error=plantonista_error,
    )


@bp.route("/contabilidade/pagamentos/novo", methods=["GET", "POST"])
@login_required
def contabilidade_pagamentos_novo():
    _ensure_accounting_access()
    clinics, accessible_ids = _accounting_accessible_clinics()
    if not clinics:
        flash('Associe-se a uma clínica antes de registrar pagamentos PJ.', 'warning')
        return redirect(url_for('contabilidade_pagamentos'))

    schema_issue = _pj_payments_schema_issue()
    if schema_issue:
        flash(schema_issue[1], 'warning')
        return redirect(
            url_for(
                'contabilidade_pagamentos',
                clinica_id=request.args.get('clinica_id'),
                mes=request.args.get('mes'),
            )
        )

    form = PJPaymentForm()
    form.payment_id = None
    _configure_pj_payment_form(form, clinics, accessible_ids)
    default_clinic_id = request.args.get('clinica_id', type=int) or clinics[0].id
    if request.method == 'GET':
        form.clinic_id.data = default_clinic_id
        form.data_servico.data = date.today()
        form.prestador_tipo.data = form.prestador_tipo.data or 'servico'

        selected_plantao_id = request.args.get('plantao_id', type=int)
        if selected_plantao_id:
            escala = PlantonistaEscala.query.get(selected_plantao_id)
            if escala and escala.clinic_id in accessible_ids:
                form.prestador_tipo.data = 'plantonista'
                _prefill_plantao_fields_on_form(form, escala)

    if form.validate_on_submit():
        clinic_id = form.clinic_id.data
        if clinic_id not in accessible_ids:
            abort(403)

        selected_plantao = (
            form.plantao_vinculado.data
            if (form.prestador_tipo.data or '').strip() == 'plantonista'
            else None
        )

        payment = PJPayment(
            clinic_id=clinic_id,
            prestador_nome=form.prestador_nome.data.strip(),
            prestador_cnpj=''.join(ch for ch in (form.prestador_cnpj.data or '') if ch.isdigit()),
            nota_fiscal_numero=(form.nota_fiscal_numero.data or '').strip() or None,
            tipo_prestador=form.tipo_prestador.data,
            plantao_horas=form.plantao_horas.data,
            valor=form.valor.data,
            data_servico=form.data_servico.data,
            data_pagamento=form.data_pagamento.data,
            observacoes=(form.observacoes.data or '').strip() or None,
        )
        payment.status = 'pago' if payment.data_pagamento else 'pendente'

        db.session.add(payment)
        db.session.flush()
        _sync_payment_plantao_link(payment, selected_plantao, form)
        db.session.flush()
        _sync_pj_payment_classification(payment)
        db.session.commit()

        flash('Pagamento PJ registrado com sucesso!', 'success')
        return redirect(
            url_for(
                'contabilidade_pagamentos',
                clinica_id=clinic_id,
                mes=_format_month_parameter(payment.data_servico),
            )
        )

    cancel_url = url_for(
        'contabilidade_pagamentos',
        clinica_id=default_clinic_id,
        mes=request.args.get('mes') or _format_month_parameter(date.today()),
    )

    return render_template(
        'contabilidade/pagamentos_form.html',
        form=form,
        form_title='Novo pagamento PJ',
        submit_label='Salvar pagamento',
        cancel_url=cancel_url,
    )


@bp.route("/contabilidade/pagamentos/<int:payment_id>/editar", methods=["GET", "POST"])
@login_required
def contabilidade_pagamentos_editar(payment_id):
    _ensure_accounting_access()
    schema_issue = _pj_payments_schema_issue()
    if schema_issue:
        flash(schema_issue[1], 'warning')
        return redirect(
            url_for(
                'contabilidade_pagamentos',
                clinica_id=request.args.get('clinica_id'),
                mes=request.args.get('mes'),
            )
        )
    payment = PJPayment.query.get_or_404(payment_id)
    clinics, accessible_ids = _accounting_accessible_clinics()
    if clinics:
        clinic_choices = [(clinic.id, clinic.nome or f'Clínica #{clinic.id}') for clinic in clinics]
    else:
        clinic_choices = [(payment.clinic_id, getattr(payment.clinic, 'nome', f'Clínica #{payment.clinic_id}'))]

    if payment.clinic_id not in accessible_ids and not _is_admin():
        abort(403)

    form_clinics = clinics or ([payment.clinic] if payment.clinic else [])
    if not form_clinics:
        form_clinics = [SimpleNamespace(id=payment.clinic_id, nome=f'Clínica #{payment.clinic_id}')]

    form = PJPaymentForm(obj=payment)
    form.payment_id = payment.id
    _configure_pj_payment_form(form, form_clinics, set(accessible_ids) | {payment.clinic_id})
    if request.method == 'GET':
        form.clinic_id.data = payment.clinic_id
        form.tipo_prestador.data = payment.tipo_prestador or 'especialista'

    current_plantao = _get_primary_payment_plantao(payment)
    if request.method == 'GET':
        form.prestador_tipo.data = 'plantonista' if current_plantao else 'servico'
        if current_plantao:
            _prefill_plantao_fields_on_form(form, current_plantao)

    if form.validate_on_submit():
        clinic_id = form.clinic_id.data
        if clinic_id not in accessible_ids and not _is_admin():
            abort(403)

        selected_plantao = (
            form.plantao_vinculado.data
            if (form.prestador_tipo.data or '').strip() == 'plantonista'
            else None
        )

        payment.clinic_id = clinic_id
        payment.prestador_nome = form.prestador_nome.data.strip()
        payment.prestador_cnpj = ''.join(ch for ch in (form.prestador_cnpj.data or '') if ch.isdigit())
        payment.nota_fiscal_numero = (form.nota_fiscal_numero.data or '').strip() or None
        payment.tipo_prestador = form.tipo_prestador.data
        payment.plantao_horas = form.plantao_horas.data
        payment.valor = form.valor.data
        payment.data_servico = form.data_servico.data
        payment.data_pagamento = form.data_pagamento.data
        payment.observacoes = (form.observacoes.data or '').strip() or None
        payment.status = 'pago' if payment.data_pagamento else 'pendente'

        db.session.flush()
        _sync_payment_plantao_link(payment, selected_plantao, form)
        db.session.flush()
        _sync_pj_payment_classification(payment)
        db.session.commit()

        flash('Pagamento PJ atualizado com sucesso!', 'success')
        return redirect(
            url_for(
                'contabilidade_pagamentos',
                clinica_id=clinic_id,
                mes=_format_month_parameter(payment.data_servico),
            )
        )

    cancel_url = url_for(
        'contabilidade_pagamentos',
        clinica_id=payment.clinic_id,
        mes=request.args.get('mes') or _format_month_parameter(payment.data_servico),
    )

    return render_template(
        'contabilidade/pagamentos_form.html',
        form=form,
        form_title='Editar pagamento PJ',
        submit_label='Atualizar pagamento',
        cancel_url=cancel_url,
        editing=True,
    )


@bp.route("/contabilidade/pagamentos/<int:payment_id>/delete", methods=["POST"])
@login_required
def contabilidade_pagamentos_delete(payment_id):
    _ensure_accounting_access()
    schema_issue = _pj_payments_schema_issue()
    if schema_issue:
        flash(schema_issue[1], 'warning')
        return redirect(
            url_for(
                'contabilidade_pagamentos',
                clinica_id=request.args.get('clinica_id'),
                mes=request.args.get('mes'),
            )
        )
    payment = PJPayment.query.get_or_404(payment_id)
    _, accessible_ids = _accounting_accessible_clinics()
    if payment.clinic_id not in accessible_ids and not _is_admin():
        abort(403)

    clinic_id = payment.clinic_id
    month_value = request.args.get('mes') or _format_month_parameter(payment.data_servico)

    _delete_pj_payment_classification(payment.id)
    db.session.delete(payment)
    db.session.commit()

    flash('Pagamento PJ excluído com sucesso.', 'success')
    return redirect(url_for('contabilidade_pagamentos', clinica_id=clinic_id, mes=month_value))


@bp.route("/contabilidade/pagamentos/<int:payment_id>/marcar_pago", methods=["POST"])
@login_required
def contabilidade_pagamentos_marcar_pago(payment_id):
    _ensure_accounting_access()
    schema_issue = _pj_payments_schema_issue()
    if schema_issue:
        flash(schema_issue[1], 'warning')
        return redirect(
            url_for(
                'contabilidade_pagamentos',
                clinica_id=request.args.get('clinica_id'),
                mes=request.args.get('mes'),
            )
        )
    payment = PJPayment.query.get_or_404(payment_id)
    _, accessible_ids = _accounting_accessible_clinics()
    if payment.clinic_id not in accessible_ids and not _is_admin():
        abort(403)

    if payment.status != 'pago':
        payment.status = 'pago'
        if not payment.data_pagamento:
            payment.data_pagamento = date.today()
        db.session.flush()
        _sync_pj_payment_classification(payment)
        db.session.commit()
        flash('Pagamento marcado como pago.', 'success')
    else:
        flash('Pagamento já estava marcado como pago.', 'info')

    month_value = request.args.get('mes') or _format_month_parameter(payment.data_servico)
    return redirect(url_for('contabilidade_pagamentos', clinica_id=payment.clinic_id, mes=month_value))


@bp.route("/contabilidade/pagamentos/plantonistas/novo", methods=["GET", "POST"])
@login_required
def contabilidade_plantonistas_novo():
    _ensure_accounting_access()
    clinics, accessible_ids = _accounting_accessible_clinics()
    if not clinics:
        flash('Associe-se a uma clínica antes de cadastrar plantões.', 'warning')
        return redirect(url_for('contabilidade_pagamentos', aba='plantonistas'))

    form = PlantonistaEscalaForm()
    _populate_plantonista_form_choices(form, clinics)
    default_clinic_id = request.args.get('clinica_id', type=int) or clinics[0].id
    plantao_modelos = _load_plantao_modelos([default_clinic_id])
    _configure_modelo_choices(form, plantao_modelos, default_clinic_id)
    if request.method == 'GET':
        form.clinic_id.data = default_clinic_id
        form.status.data = 'agendado'
        default_day = date.today()
        requested_day = request.args.get('dia')
        if requested_day:
            try:
                default_day = date.fromisoformat(requested_day)
            except ValueError:
                pass
        form.data_inicio.data = default_day

        selected_modelo_id = request.args.get('modelo_id', type=int)
        if selected_modelo_id:
            modelo = next((m for m in plantao_modelos if m.id == selected_modelo_id), None)
            if modelo and modelo.clinic_id == form.clinic_id.data:
                _apply_modelo_to_form(form, modelo)

        requested_medico_id = request.args.get('medico_id', type=int)
        if requested_medico_id is not None:
            form.medico_id.data = requested_medico_id

    if form.validate_on_submit():
        clinic_id = form.clinic_id.data
        if clinic_id not in accessible_ids and not _is_admin():
            abort(403)

        if form.plantao_modelo_id.data == 0:
            form.plantao_modelo_id.data = None

        medico_id = form.medico_id.data or None
        if medico_id == 0:
            medico_id = None
        medico_nome = (form.medico_nome.data or '').strip()
        medico_cnpj = ''.join(ch for ch in (form.medico_cnpj.data or '') if ch.isdigit()) or None

        inicio = datetime.combine(form.data_inicio.data, form.hora_inicio.data)
        fim = datetime.combine(form.data_inicio.data, form.hora_fim.data)
        if fim <= inicio:
            fim += timedelta(days=1)
        horas_previstas = _compute_plantao_horas(inicio, fim)

        novo_modelo = _build_modelo_from_form(form)

        escala = PlantonistaEscala(
            clinic_id=clinic_id,
            medico_id=medico_id,
            medico_nome=medico_nome,
            medico_cnpj=medico_cnpj,
            turno=form.turno.data.strip(),
            inicio=inicio,
            fim=fim,
            plantao_horas=horas_previstas,
            valor_previsto=form.valor_previsto.data,
            status=form.status.data,
            nota_fiscal_recebida=form.nota_fiscal_recebida.data,
            retencao_validada=form.retencao_validada.data,
            observacoes=(form.observacoes.data or '').strip() or None,
        )
        if escala.status == 'realizado' and escala.realizado_em is None:
            escala.realizado_em = utcnow()

        if novo_modelo:
            db.session.add(novo_modelo)
        db.session.add(escala)
        db.session.commit()

        if novo_modelo:
            flash('Modelo de plantão salvo para a clínica.', 'success')

        flash('Plantão cadastrado com sucesso.', 'success')
        return redirect(
            url_for(
                'contabilidade_pagamentos',
                clinica_id=clinic_id,
                mes=_format_month_parameter(inicio),
                aba='plantonistas',
            )
        )

    cancel_url = url_for(
        'contabilidade_pagamentos',
        clinica_id=default_clinic_id,
        mes=request.args.get('mes') or _format_month_parameter(date.today()),
        aba='plantonistas',
    )

    plantao_modelos_data = [_serialize_plantao_modelo(modelo) for modelo in plantao_modelos]

    return render_template(
        'contabilidade/plantonistas_form.html',
        form=form,
        form_title='Cadastrar plantão',
        submit_label='Salvar plantão',
        cancel_url=cancel_url,
        plantao_modelos=plantao_modelos_data,
    )


@bp.route("/contabilidade/pagamentos/plantonistas/quick-create", methods=["POST"])
@login_required
def contabilidade_plantonistas_quick_create():
    _ensure_accounting_access()
    clinics, accessible_ids = _accounting_accessible_clinics()
    if not clinics:
        return jsonify({'error': 'Associe-se a uma clínica antes de cadastrar plantões.'}), 400

    data = request.get_json(silent=True) or request.form

    def _parse_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    clinic_id = _parse_int(data.get('clinica_id') if hasattr(data, 'get') else None)
    modelo_id = _parse_int(data.get('modelo_id') if hasattr(data, 'get') else None)
    dia_value = data.get('dia') if hasattr(data, 'get') else None
    medico_id = _parse_int(data.get('medico_id') if hasattr(data, 'get') else None)
    recorrencia = (data.get('recorrencia') if hasattr(data, 'get') else '') or ''
    recorrencia_total = _parse_int(data.get('recorrencia_total') if hasattr(data, 'get') else None) or 1

    recorrencia_total = max(1, min(recorrencia_total, 12))

    if not clinic_id:
        return jsonify({'error': 'Clínica não informada.'}), 400
    if clinic_id not in accessible_ids and not _is_admin():
        return jsonify({'error': 'Você não tem acesso a esta clínica.'}), 403
    if not modelo_id:
        return jsonify({'error': 'Selecione um modelo válido para agendar.'}), 400

    modelo = PlantaoModelo.query.get_or_404(modelo_id)
    if modelo.clinic_id != clinic_id:
        return jsonify({'error': 'O modelo selecionado pertence a outra clínica.'}), 400

    try:
        dia = date.fromisoformat(dia_value)
    except Exception:
        return jsonify({'error': 'Data do plantão inválida.'}), 400

    if not modelo.hora_inicio:
        return jsonify({'error': 'O modelo selecionado não possui horário de início.'}), 400

    datas_agendar: list[date] = [dia]
    if recorrencia.lower() in {'semanal', 'mensal', 'quinzenal'}:
        next_date = dia
        for _ in range(recorrencia_total - 1):
            if recorrencia.lower() == 'semanal':
                next_date = next_date + timedelta(weeks=1)
            elif recorrencia.lower() == 'quinzenal':
                next_date = next_date + timedelta(days=14)
            else:
                next_date = next_date + relativedelta(months=1)
            datas_agendar.append(next_date)

    escalas_criadas = []
    for data_agenda in datas_agendar:
        inicio = datetime.combine(data_agenda, modelo.hora_inicio)
        fim = inicio + timedelta(hours=float(modelo.duracao_horas or 0))
        horas_previstas = _compute_plantao_horas(inicio, fim)
        if not horas_previstas:
            continue

    medico_nome = (modelo.medico_nome or '').strip()
    medico_cnpj = (modelo.medico_cnpj or '').strip() or None
    medico_db_id = None

    if medico_id:
        medico = Veterinario.query.get(medico_id)
        if not medico:
            return jsonify({'error': 'Médico selecionado não encontrado.'}), 404
        medico_db_id = medico.id
        medico_nome = medico.user.name if medico.user else (medico_nome or f'Veterinário #{medico_id}')
    elif modelo.medico_id:
        medico_db_id = modelo.medico_id

    if not medico_nome:
        return jsonify({'error': 'Defina o profissional responsável pelo plantão.'}), 400

        escala = PlantonistaEscala(
            clinic_id=clinic_id,
            medico_id=medico_db_id,
            medico_nome=medico_nome,
            medico_cnpj=medico_cnpj,
            turno=modelo.nome,
            inicio=inicio,
            fim=fim,
            plantao_horas=horas_previstas,
            valor_previsto=Decimal('0.00'),
            status='agendado',
            nota_fiscal_recebida=False,
            retencao_validada=False,
        )

        db.session.add(escala)
        escalas_criadas.append(escala)

    if not escalas_criadas:
        return jsonify({'error': 'Nenhum plantão pôde ser criado a partir do modelo.'}), 400

    db.session.commit()

    redirect_url = url_for(
        'contabilidade_pagamentos',
        clinica_id=clinic_id,
        mes=_format_month_parameter(inicio),
        aba='plantonistas',
    )

    return jsonify({
        'message': 'Plantão agendado com o modelo selecionado.',
        'total_criado': len(escalas_criadas),
        'redirect': redirect_url,
    })


@bp.route("/contabilidade/pagamentos/plantonistas/<int:escala_id>/editar", methods=["GET", "POST"])
@login_required
def contabilidade_plantonistas_editar(escala_id):
    _ensure_accounting_access()
    escala = PlantonistaEscala.query.get_or_404(escala_id)
    clinics, accessible_ids = _accounting_accessible_clinics()
    if escala.clinic_id not in accessible_ids and not _is_admin():
        abort(403)

    form = PlantonistaEscalaForm(obj=escala)
    _populate_plantonista_form_choices(form, clinics or [escala.clinic])
    plantao_modelos = _load_plantao_modelos([escala.clinic_id])
    _configure_modelo_choices(form, plantao_modelos, escala.clinic_id)

    if request.method == 'GET':
        form.clinic_id.data = escala.clinic_id
        form.medico_id.data = escala.medico_id or 0
        form.medico_nome.data = escala.medico_nome
        form.medico_cnpj.data = escala.medico_cnpj
        form.turno.data = escala.turno
        form.data_inicio.data = escala.inicio.date()
        form.hora_inicio.data = escala.inicio.time().replace(microsecond=0)
        form.hora_fim.data = escala.fim.time().replace(microsecond=0)
        form.valor_previsto.data = escala.valor_previsto
        form.status.data = escala.status
        form.nota_fiscal_recebida.data = escala.nota_fiscal_recebida
        form.retencao_validada.data = escala.retencao_validada
        form.observacoes.data = escala.observacoes

        selected_modelo_id = request.args.get('modelo_id', type=int)
        if selected_modelo_id:
            modelo = next((m for m in plantao_modelos if m.id == selected_modelo_id), None)
            if modelo and modelo.clinic_id == form.clinic_id.data:
                _apply_modelo_to_form(form, modelo)

    if form.validate_on_submit():
        clinic_id = form.clinic_id.data
        if clinic_id not in accessible_ids and not _is_admin():
            abort(403)

        if form.plantao_modelo_id.data == 0:
            form.plantao_modelo_id.data = None

        medico_id = form.medico_id.data or None
        if medico_id == 0:
            medico_id = None
        escala.clinic_id = clinic_id
        escala.medico_id = medico_id
        escala.medico_nome = (form.medico_nome.data or '').strip()
        escala.medico_cnpj = ''.join(ch for ch in (form.medico_cnpj.data or '') if ch.isdigit()) or None
        escala.turno = form.turno.data.strip()
        inicio = datetime.combine(form.data_inicio.data, form.hora_inicio.data)
        fim = datetime.combine(form.data_inicio.data, form.hora_fim.data)
        if fim <= inicio:
            fim += timedelta(days=1)
        escala.inicio = inicio
        escala.fim = fim
        escala.plantao_horas = _compute_plantao_horas(inicio, fim)
        escala.valor_previsto = form.valor_previsto.data
        escala.status = form.status.data
        if escala.status == 'realizado' and not escala.realizado_em:
            escala.realizado_em = utcnow()
        elif escala.status != 'realizado':
            escala.realizado_em = None
        escala.nota_fiscal_recebida = form.nota_fiscal_recebida.data
        escala.retencao_validada = form.retencao_validada.data
        escala.observacoes = (form.observacoes.data or '').strip() or None

        novo_modelo = _build_modelo_from_form(form)
        if novo_modelo:
            db.session.add(novo_modelo)

        db.session.commit()
        if novo_modelo:
            flash('Modelo de plantão salvo para a clínica.', 'success')
        flash('Plantão atualizado com sucesso.', 'success')
        return redirect(
            url_for(
                'contabilidade_pagamentos',
                clinica_id=clinic_id,
                mes=_format_month_parameter(escala.inicio),
                aba='plantonistas',
            )
        )

    cancel_url = url_for(
        'contabilidade_pagamentos',
        clinica_id=escala.clinic_id,
        mes=request.args.get('mes') or _format_month_parameter(escala.inicio),
        aba='plantonistas',
    )

    plantao_modelos_data = [_serialize_plantao_modelo(modelo) for modelo in plantao_modelos]

    return render_template(
        'contabilidade/plantonistas_form.html',
        form=form,
        form_title='Editar plantão',
        submit_label='Atualizar plantão',
        cancel_url=cancel_url,
        editing=True,
        plantao_modelos=plantao_modelos_data,
    )


@bp.route("/contabilidade/pagamentos/plantao/<int:escala_id>/confirmar", methods=["POST"])
@login_required
def contabilidade_plantao_confirmar(escala_id):
    _ensure_accounting_access()
    escala = PlantonistaEscala.query.get_or_404(escala_id)
    _, accessible_ids = _accounting_accessible_clinics()
    if escala.clinic_id not in accessible_ids and not _is_admin():
        abort(403)

    if escala.status != 'realizado':
        escala.status = 'realizado'
        escala.realizado_em = utcnow()
        db.session.commit()
        flash('Plantão confirmado como realizado.', 'success')
    else:
        flash('Plantão já estava marcado como realizado.', 'info')

    month_value = _format_month_parameter(escala.inicio)
    return redirect(
        url_for(
            'contabilidade_pagamentos',
            clinica_id=escala.clinic_id,
            mes=month_value,
            aba='plantonistas',
        )
    )


@bp.route("/contabilidade/pagamentos/plantao/<int:escala_id>/gerar_pagamento", methods=["POST"])
@login_required
def contabilidade_plantao_gerar_pagamento(escala_id):
    _ensure_accounting_access()
    escala = PlantonistaEscala.query.get_or_404(escala_id)
    _, accessible_ids = _accounting_accessible_clinics()
    if escala.clinic_id not in accessible_ids and not _is_admin():
        abort(403)

    if escala.pj_payment_id:
        flash('Este plantão já possui um pagamento vinculado.', 'info')
    else:
        if not escala.nota_fiscal_recebida or not escala.retencao_validada:
            flash('Valide a nota fiscal e retenções antes de gerar o pagamento.', 'warning')
        else:
            cnpj = ''.join(ch for ch in (escala.medico_cnpj or '') if ch.isdigit())
            if len(cnpj) != 14:
                flash('Informe um CNPJ válido para o médico antes de gerar o pagamento.', 'warning')
            else:
                payment = PJPayment(
                    clinic_id=escala.clinic_id,
                    prestador_nome=escala.medico_nome,
                    prestador_cnpj=cnpj,
                    nota_fiscal_numero=None,
                    valor=escala.valor_previsto,
                    data_servico=escala.inicio.date(),
                    data_pagamento=date.today() if escala.status == 'realizado' else None,
                    observacoes=escala.observacoes,
                )
                payment.status = 'pago' if payment.data_pagamento else 'pendente'
                horas_previstas = escala.plantao_horas or escala.horas_previstas
                if horas_previstas and horas_previstas > 0:
                    payment.plantao_horas = horas_previstas
                payment.tipo_prestador = 'plantonista'
                db.session.add(payment)
                db.session.flush()
                escala.pj_payment = payment
                db.session.flush()
                _sync_pj_payment_classification(payment)
                db.session.commit()
                flash('Pagamento PJ gerado a partir do plantão.', 'success')

    return redirect(
        url_for(
            'contabilidade_pagamentos',
            clinica_id=escala.clinic_id,
            mes=_format_month_parameter(escala.inicio),
            aba='plantonistas',
        )
    )


@bp.route("/contabilidade/obrigacoes", methods=["GET"])
@login_required
def contabilidade_obrigacoes():
    _ensure_accounting_access()
    clinics, accessible_ids = _accounting_accessible_clinics()

    requested_clinic_id = request.args.get('clinica_id', type=int)
    selected_clinic = _select_accounting_clinic(
        clinics,
        accessible_ids,
        requested_clinic_id=requested_clinic_id,
    )

    month_param = request.args.get('month') or request.args.get('mes')
    if month_param:
        normalized_month = month_param[:7]
    else:
        normalized_month = None
    selected_month = _parse_month_parameter(normalized_month)

    current_month = date.today().replace(day=1)
    month_names_pt = [
        'janeiro',
        'fevereiro',
        'março',
        'abril',
        'maio',
        'junho',
        'julho',
        'agosto',
        'setembro',
        'outubro',
        'novembro',
        'dezembro',
    ]
    months_list = []
    for idx in range(12):
        month_date = current_month - relativedelta(months=idx)
        months_list.append(
            {
                'value': month_date.strftime('%Y-%m-01'),
                'label': f"{month_names_pt[month_date.month - 1].capitalize()} de {month_date.year}",
            }
        )

    selected_month_value = selected_month.strftime('%Y-%m-01')
    selected_month_label = next(
        (option['label'] for option in months_list if option['value'] == selected_month_value),
        f"{month_names_pt[selected_month.month - 1].capitalize()} de {selected_month.year}",
    )

    clinic_taxes = None
    if selected_clinic:
        clinic_taxes = ClinicTaxes.query.filter_by(
            clinic_id=selected_clinic.id,
            month=selected_month,
        ).first()

    return render_template(
        'contabilidade/obrigacoes.html',
        clinics=clinics,
        selected_clinic=selected_clinic,
        clinic_taxes=clinic_taxes,
        months_list=months_list,
        selected_month=selected_month,
        selected_month_value=selected_month_value,
        selected_month_label=selected_month_label,
    )


@bp.route("/contabilidade/nfse", methods=["GET"])
@login_required
def contabilidade_nfse():
    _ensure_accounting_access()
    clinics, accessible_ids = _accounting_accessible_clinics()

    requested_id = request.args.get('clinica_id', type=int)
    orcamento_id = request.args.get('orcamento_id', type=int)
    atendimento_id = request.args.get('atendimento_id', type=int)
    origin_param = "orcamento_id" if orcamento_id else ("atendimento_id" if atendimento_id else None)
    origin_id = orcamento_id or atendimento_id
    if requested_id and requested_id not in accessible_ids and not _is_admin():
        abort(403)
    visible_clinics = clinics
    if not _is_admin():
        visible_clinics = [clinic for clinic in clinics if clinic.id in accessible_ids]
    selected_clinic = _select_accounting_clinic(
        visible_clinics,
        accessible_ids,
        requested_clinic_id=requested_id,
    )
    selected_clinic_id = selected_clinic.id if selected_clinic else None

    status_filter = (request.args.get('status') or '').strip().lower()
    issues = []
    queue_count = 0
    pdf_issue_ids: set[int] = set()
    if selected_clinic_id:
        query = NfseIssue.query.filter_by(clinica_id=selected_clinic_id)
        if status_filter:
            query = query.filter(NfseIssue.status == status_filter)
        issues = query.order_by(NfseIssue.created_at.desc()).limit(200).all()
        queue_count = (
            NfseIssue.query
            .filter_by(clinica_id=selected_clinic_id, status="fila")
            .count()
        )
        if issues:
            issue_ids = [issue.id for issue in issues]
            pdf_issue_ids = {
                row.nfse_issue_id
                for row in (
                    NfseXml.query
                    .filter(NfseXml.nfse_issue_id.in_(issue_ids))
                    .filter(NfseXml.tipo.ilike("%pdf%"))
                    .all()
                )
            }

    statuses = [
        "fila",
        "processando",
        "pendente",
        "autorizado",
        "erro",
        "cancelada",
        "cancelamento_solicitado",
        "substituicao_solicitada",
    ]

    municipio_options = [
        {"value": "", "label": "Selecione um município"},
        {"value": "orlandia", "label": "Orlândia (SP)"},
        {"value": "belo_horizonte", "label": "Belo Horizonte (MG)"},
        {"value": "contagem", "label": "Contagem (MG)"},
    ]

    def _nfse_setup_resources(municipio_key: str):
        default_resources = {
            "wizard_url": url_for("fiscal_onboarding_step", step=1),
            "links": [],
        }
        if municipio_key == "belo_horizonte":
            return {
                "wizard_url": url_for("fiscal_onboarding_step", step=1),
                "links": [
                    {
                        "title": "PBH - NFS-e Nacional",
                        "description": "Pagina oficial da PBH sobre adesao, migracao e obrigatoriedade de emissores.",
                        "url": "https://fazenda.pbh.gov.br/nfse/adn/",
                    },
                    {
                        "title": "Documentacao tecnica nacional",
                        "description": "Leiautes, schemas e manuais atuais da NFS-e Nacional.",
                        "url": "https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/documentacao-atual",
                    },
                    {
                        "title": "APIs da NFS-e Nacional",
                        "description": "Ambientes de producao restrita e producao para emissao por API.",
                        "url": "https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao",
                    },
                    {
                        "title": "Emissor Nacional",
                        "description": "Portal oficial para conferencias e operacao assistida do contribuinte.",
                        "url": "https://www.nfse.gov.br/EmissorNacional/",
                    },
                ],
                "field_hints": {
                    "municipio_ibge": "3106200",
                    "uf": "MG",
                },
            }
        if municipio_key == "contagem":
            return {
                "wizard_url": url_for("fiscal_onboarding_step", step=1),
                "links": [
                    {
                        "title": "Contagem - Receita Municipal",
                        "description": "Portal oficial da Secretaria Municipal de Fazenda para NFS-e e webservices.",
                        "url": "https://fazenda.contagem.mg.gov.br/nfe/",
                    },
                    {
                        "title": "Emissor webservice de Contagem",
                        "description": "Ambiente de producao informado pela prefeitura para a nova solucao de NFS-e.",
                        "url": "https://nfse-contagem.cidade360.cloud",
                    },
                    {
                        "title": "Documentacao tecnica nacional",
                        "description": "Leiautes, schemas e manuais do padrao nacional da NFS-e.",
                        "url": "https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/documentacao-atual",
                    },
                ],
                "field_hints": {
                    "municipio_ibge": "3118601",
                    "uf": "MG",
                },
            }
        if municipio_key != "orlandia":
            return default_resources
        return {
            "wizard_url": url_for("fiscal_onboarding_step", step=1),
            "links": [
                {
                    "title": "Portal oficial da NFS-e",
                    "description": "Acesso principal da prefeitura para emissão e escrituração eletrônica.",
                    "url": "https://www.orlandia.sp.gov.br/novo/servicos/nota-fiscal-eletronica",
                },
                {
                    "title": "Termo de opção para emissão",
                    "description": "Pedido de autorização para começar a emitir NFS-e quando a prefeitura exigir deferimento prévio.",
                    "url": "https://www.orlandia.sp.gov.br/novo/servicos/nota-fiscal-eletronica",
                },
                {
                    "title": "Requerimento para solicitação de senha",
                    "description": "Formulário citado pela prefeitura para liberação da senha de segurança do emissor.",
                    "url": "https://www.orlandia.sp.gov.br/novo/servicos/nota-fiscal-eletronica",
                },
                {
                    "title": "Liberação do Cidadão Web",
                    "description": "A prefeitura informa que o Anexo IV deve ser entregue à Divisão de Tributação para liberar o acesso web.",
                    "url": "https://www.orlandia.sp.gov.br/novo/cidadao-web",
                },
                {
                    "title": "Acesso Betha / e-gov",
                    "description": "Entrada do sistema web usado pelo município para operação diária após a liberação.",
                    "url": "https://e-gov.betha.com.br/",
                },
            ],
            "field_hints": {
                "municipio_ibge": "3534302",
                "uf": "SP",
            },
        }

    nfse_settings = {}
    nfse_missing_fields = []
    nfse_setup_resources = {"wizard_url": url_for("fiscal_onboarding_step", step=1), "links": []}
    if selected_clinic:
        nfse_settings = {
            "municipio_nfse": get_clinica_field(selected_clinic, "municipio_nfse", "") or "",
            "inscricao_municipal": get_clinica_field(selected_clinic, "inscricao_municipal", "") or "",
            "inscricao_estadual": get_clinica_field(selected_clinic, "inscricao_estadual", "") or "",
            "regime_tributario": get_clinica_field(selected_clinic, "regime_tributario", "") or "",
            "cnae": get_clinica_field(selected_clinic, "cnae", "") or "",
            "codigo_servico": get_clinica_field(selected_clinic, "codigo_servico", "") or "",
            "aliquota_iss": get_clinica_field(selected_clinic, "aliquota_iss", "") or "",
            "nfse_username": get_clinica_field(selected_clinic, "nfse_username", "") or "",
            "nfse_cert_path": get_clinica_field(selected_clinic, "nfse_cert_path", "") or "",
            "nfse_token": get_clinica_field(selected_clinic, "nfse_token", "") or "",
        }
        nfse_missing_fields, _municipio_key = _nfse_missing_fields(selected_clinic)
        nfse_setup_resources = _nfse_setup_resources(_municipio_key)

    return render_template(
        'contabilidade/nfse.html',
        clinics=visible_clinics,
        selected_clinic=selected_clinic,
        issues=issues,
        statuses=statuses,
        status_filter=status_filter,
        queue_count=queue_count,
        pdf_issue_ids=pdf_issue_ids,
        origin_param=origin_param,
        origin_id=origin_id,
        municipio_options=municipio_options,
        nfse_settings=nfse_settings,
        nfse_missing_fields=nfse_missing_fields,
        fiscal_master_key_configured=bool((os.getenv("FISCAL_MASTER_KEY") or "").strip()),
        nfse_setup_resources=nfse_setup_resources,
        cancel_rules=(
            get_nfse_cancel_rules(get_clinica_field(selected_clinic, "municipio_nfse", ""))
            if selected_clinic
            else None
        ),
        async_enabled=bool(
            selected_clinic
            and should_emit_async(get_clinica_field(selected_clinic, "municipio_nfse", ""))
        ),
    )


@bp.route("/contabilidade/nfse/configurar", methods=["POST"])
@login_required
def contabilidade_nfse_configurar():
    _ensure_accounting_access()
    clinic_id = request.form.get('clinica_id', type=int)
    orcamento_id = request.form.get('orcamento_id', type=int)
    atendimento_id = request.form.get('atendimento_id', type=int)
    origin_param = "orcamento_id" if orcamento_id else ("atendimento_id" if atendimento_id else None)
    origin_id = orcamento_id or atendimento_id
    _, accessible_ids = _accounting_accessible_clinics()
    if clinic_id and clinic_id not in accessible_ids:
        abort(403)

    clinic = Clinica.query.get_or_404(clinic_id) if clinic_id else None
    if not clinic:
        flash("Selecione uma clínica para atualizar as configurações.", "warning")
        return redirect(url_for('contabilidade_nfse'))

    decimal_fields = {
        "aliquota_iss",
        "aliquota_pis",
        "aliquota_cofins",
        "aliquota_csll",
        "aliquota_ir",
    }
    password_fields = {"nfse_password", "nfse_cert_password"}
    sensitive_fields = {
        "nfse_username",
        "nfse_password",
        "nfse_cert_path",
        "nfse_cert_password",
        "nfse_token",
    }
    updatable_fields = [
        "municipio_nfse",
        "inscricao_municipal",
        "inscricao_estadual",
        "regime_tributario",
        "cnae",
        "codigo_servico",
        "aliquota_iss",
        "aliquota_pis",
        "aliquota_cofins",
        "aliquota_csll",
        "aliquota_ir",
        "nfse_username",
        "nfse_password",
        "nfse_cert_path",
        "nfse_cert_password",
        "nfse_token",
    ]

    for field_name in updatable_fields:
        if not clinica_has_column(field_name):
            continue
        value = request.form.get(field_name)
        if field_name in password_fields and not value:
            continue
        if value is not None and isinstance(value, str):
            value = value.strip()
        if field_name in decimal_fields:
            if value in (None, ""):
                value = None
            else:
                try:
                    value = Decimal(value.replace(",", "."))
                except (AttributeError, InvalidOperation):
                    flash("Informe uma alíquota válida.", "warning")
                    return redirect(
                        url_for(
                            'contabilidade_nfse',
                            clinica_id=clinic_id,
                            **({origin_param: origin_id} if origin_param else {}),
                        )
                    )
        else:
            if value == "":
                value = None
        if value is not None and field_name in sensitive_fields:
            try:
                value = encrypt_text(value)
            except MissingMasterKeyError:
                flash(
                    "Chave fiscal não configurada. Configure FISCAL_MASTER_KEY antes de salvar.",
                    "danger",
                )
                return redirect(
                    url_for(
                        'contabilidade_nfse',
                        clinica_id=clinic_id,
                        **({origin_param: origin_id} if origin_param else {}),
                    )
                )
        setattr(clinic, field_name, value)

    db.session.add(clinic)
    try:
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("Erro ao salvar configurações da NFS-e")
        flash("Não foi possível salvar as configurações. Tente novamente.", "danger")
    else:
        municipio_key = (get_clinica_field(clinic, "municipio_nfse", "") or "").strip().lower()
        required_by_municipio = _nfse_required_fields_by_municipio()
        labels = _nfse_field_labels()
        missing_fields = []
        for field in required_by_municipio.get(municipio_key, []):
            if get_clinica_field(clinic, field, "") in (None, "", []):
                missing_fields.append(labels.get(field, field))
        if missing_fields:
            flash(
                "Configurações salvas, mas faltam dados obrigatórios: "
                + ", ".join(missing_fields)
                + ".",
                "warning",
            )
        else:
            flash("Configurações da NFS-e atualizadas com sucesso.", "success")

    return redirect(
        url_for(
            'contabilidade_nfse',
            clinica_id=clinic_id,
            **({origin_param: origin_id} if origin_param else {}),
        )
    )


@bp.route("/contabilidade/nfse/orcamento/<int:orcamento_id>", methods=["GET"])
@login_required
def contabilidade_nfse_orcamento(orcamento_id: int):
    _ensure_accounting_access()
    _, accessible_ids = _accounting_accessible_clinics()
    orcamento = (
        Orcamento.query
        .options(
            joinedload(Orcamento.consulta)
            .joinedload(Consulta.animal)
            .joinedload(Animal.owner),
        )
        .get(orcamento_id)
    )
    if not orcamento:
        return jsonify({"error": "Orçamento não encontrado."}), 404
    if orcamento.clinica_id not in accessible_ids:
        return jsonify({"error": "Sem acesso ao orçamento informado."}), 403

    payload = _build_nfse_orcamento_payload(orcamento)
    return jsonify(payload)


@bp.route("/contabilidade/nfse/preview", methods=["GET"])
@login_required
def contabilidade_nfse_preview():
    _ensure_accounting_access()
    orcamento_id = request.args.get("orcamento_id", type=int)
    if not orcamento_id:
        flash("Informe o orçamento para pré-visualizar a NFS-e.", "warning")
        return redirect(url_for("contabilidade_nfse"))

    orcamento = (
        Orcamento.query
        .options(
            joinedload(Orcamento.consulta)
            .joinedload(Consulta.animal)
            .joinedload(Animal.owner),
            joinedload(Orcamento.clinica),
        )
        .get(orcamento_id)
    )
    if not orcamento:
        flash("Orçamento não encontrado.", "danger")
        return redirect(url_for("contabilidade_nfse"))

    _, accessible_ids = _accounting_accessible_clinics()
    if orcamento.clinica_id not in accessible_ids:
        abort(403)

    consulta = orcamento.consulta
    animal = consulta.animal if consulta else None
    tutor = animal.owner if animal else None
    clinica = orcamento.clinica
    municipio = get_clinica_field(clinica, "municipio_nfse", "") or ""
    municipio_key = _normalize_municipio(municipio) if municipio else ""
    municipio_labels = {
        "orlandia": "Orlândia (SP)",
        "belo_horizonte": "Belo Horizonte (MG)",
    }
    municipio_label = municipio_labels.get(municipio_key, municipio or "Não informado")

    nfse_missing_fields, municipio_key = _nfse_missing_fields(clinica)
    cadastro_ok = not nfse_missing_fields
    certificado_ok, certificado_msg = _nfse_certificate_status(clinica, municipio_key)
    betha_ok, betha_msg = _nfse_betha_status(clinica, municipio_key)

    checks = [
        {"label": "Certificado válido", "ok": certificado_ok, "detail": certificado_msg},
        {
            "label": "Cadastro fiscal completo",
            "ok": cadastro_ok,
            "detail": "Todos os dados obrigatórios estão preenchidos."
            if cadastro_ok
            else "Faltam informações obrigatórias.",
        },
        {
            "label": "Comunicacao NFS-e Nacional disponivel"
            if municipio_key in NFSE_NACIONAL_MUNICIPIO_IBGE_BY_KEY
            else "Comunicação Betha disponível",
            "ok": betha_ok,
            "detail": betha_msg,
        },
    ]

    blocking_errors = []
    if not consulta:
        blocking_errors.append("O orçamento não está vinculado a uma consulta.")
    if nfse_missing_fields:
        blocking_errors.append(
            "Cadastro fiscal incompleto: "
            + ", ".join(nfse_missing_fields)
            + ". Atualize as configurações da NFS-e."
        )
    if not certificado_ok:
        blocking_errors.append("Certificado fiscal inválido ou ausente. Atualize o certificado antes de emitir.")
    if not betha_ok:
        blocking_errors.append(
            "Teste de comunicacao com a NFS-e Nacional pendente."
            if municipio_key in NFSE_NACIONAL_MUNICIPIO_IBGE_BY_KEY
            else "Teste de comunicação com a Betha pendente. Finalize o wizard fiscal."
        )

    can_emit = bool(consulta) and cadastro_ok and certificado_ok and betha_ok

    emission_result = None
    if request.args.get("emissao") == "1" and consulta:
        issue = NfseIssue.query.filter_by(
            clinica_id=clinica.id,
            internal_identifier=f"consulta:{consulta.id}",
        ).order_by(NfseIssue.created_at.desc()).first()
        if issue and issue.numero_nfse:
            emission_result = {
                "status": "success",
                "title": f"Nota Fiscal nº {issue.numero_nfse}",
                "subtitle": f"Consulta – {animal.name if animal else 'Paciente'}"
                f" (tutora {tutor.name if tutor else 'não informada'})",
                "suggestion": "Você pode baixar o PDF/XML na lista de emissões.",
            }
        elif issue and (issue.status == "erro" or issue.erro_mensagem):
            reason = issue.erro_mensagem or "Não foi possível emitir a nota."
            emission_result = {
                "status": "error",
                "title": "Não foi possível emitir a nota",
                "subtitle": f"Motivo: {reason}",
                "suggestion": (
                    "Sugestão: revise o item de serviço e o cadastro fiscal "
                    "nas configurações da NFS-e e tente novamente."
                ),
            }
        else:
            emission_result = {
                "status": "info",
                "title": "Emissão enviada para processamento",
                "subtitle": (
                    "A nota foi enviada e está sendo processada. "
                    "Acompanhe o status na listagem de emissões."
                ),
                "suggestion": "Aguarde alguns instantes e atualize a tela.",
            }

    return render_template(
        "contabilidade/nfse_preview.html",
        orcamento=orcamento,
        consulta=consulta,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        municipio_label=municipio_label,
        checks=checks,
        blocking_errors=blocking_errors,
        can_emit=can_emit,
        emission_result=emission_result,
    )


@bp.route("/contabilidade/nfse/consolidado", methods=["GET"])
@login_required
def contabilidade_nfse_consolidado():
    _ensure_accounting_access()
    clinica_id = request.args.get("clinica_id", type=int)
    orcamento_id = request.args.get("orcamento_id", type=int)
    if not clinica_id or not orcamento_id:
        return jsonify({"error": "Informe clinica_id e orcamento_id."}), 400

    _, accessible_ids = _accounting_accessible_clinics()
    if clinica_id not in accessible_ids:
        return jsonify({"error": "Sem acesso à clínica informada."}), 403

    clinica = Clinica.query.get(clinica_id)
    if not clinica:
        return jsonify({"error": "Clínica não encontrada."}), 404

    orcamento = (
        Orcamento.query
        .options(
            joinedload(Orcamento.consulta)
            .joinedload(Consulta.animal)
            .joinedload(Animal.owner),
        )
        .get(orcamento_id)
    )
    if not orcamento:
        return jsonify({"error": "Orçamento não encontrado."}), 404
    if orcamento.clinica_id not in accessible_ids:
        return jsonify({"error": "Sem acesso ao orçamento informado."}), 403
    if orcamento.clinica_id != clinica_id:
        return jsonify({"error": "Orçamento não pertence à clínica informada."}), 400

    payload = _build_nfse_orcamento_payload(orcamento)
    payload["emissor"] = _build_nfse_emissor_payload(clinica)
    return jsonify(payload)


@bp.route("/contabilidade/nfse/emitir", methods=["POST"])
@login_required
def contabilidade_nfse_emitir():
    _ensure_accounting_access()
    consulta_id = request.form.get('consulta_id', type=int)
    orcamento_id = request.form.get('orcamento_id', type=int)
    atendimento_id = request.form.get('atendimento_id', type=int)
    origin_param = "orcamento_id" if orcamento_id else ("atendimento_id" if atendimento_id else None)
    origin_id = orcamento_id or atendimento_id
    orcamento = None
    if orcamento_id:
        orcamento = Orcamento.query.options(joinedload(Orcamento.consulta)).get(orcamento_id)
        if orcamento and not consulta_id:
            consulta_id = orcamento.consulta_id
    if not consulta_id:
        flash('Informe a consulta para emitir a NFS-e.', 'warning')
        return redirect(url_for('contabilidade_nfse', **({origin_param: origin_id} if origin_param else {})))

    consulta = Consulta.query.get_or_404(consulta_id)
    _, accessible_ids = _accounting_accessible_clinics()
    if consulta.clinica_id not in accessible_ids:
        abort(403)
    if orcamento is None and consulta.orcamento:
        orcamento = consulta.orcamento

    nfse_missing_fields, municipio_key = _nfse_missing_fields(consulta.clinica)
    cadastro_ok = not nfse_missing_fields
    certificado_ok, _certificado_msg = _nfse_certificate_status(consulta.clinica, municipio_key)
    betha_ok, _betha_msg = _nfse_betha_status(consulta.clinica, municipio_key)
    if not (cadastro_ok and certificado_ok and betha_ok):
        flash("Antes de emitir, revise as pendências fiscais na pré-visualização.", "warning")
        if orcamento:
            return redirect(url_for("contabilidade_nfse_preview", orcamento_id=orcamento.id))
        return redirect(url_for('contabilidade_nfse', **({origin_param: origin_id} if origin_param else {})))

    issue = ensure_nfse_issue_for_consulta(consulta)
    if not issue:
        flash('A clínica não possui município NFS-e configurado.', 'warning')
        return redirect(
            url_for(
                'contabilidade_nfse',
                clinica_id=consulta.clinica_id,
                **({origin_param: origin_id} if origin_param else {}),
            )
        )

    payload = {"consulta_id": consulta.id}
    tomador_payload = {
        "nome": request.form.get('tomador_nome') or None,
        "cpf_cnpj": request.form.get('tomador_documento') or None,
        "email": request.form.get('tomador_email') or None,
        "telefone": request.form.get('tomador_telefone') or None,
    }
    endereco_payload = {
        "cep": request.form.get('tomador_cep') or None,
        "cidade": request.form.get('tomador_municipio') or None,
        "estado": request.form.get('tomador_uf') or None,
        "logradouro": request.form.get('tomador_logradouro') or None,
        "numero": request.form.get('tomador_numero') or None,
        "bairro": request.form.get('tomador_bairro') or None,
    }
    if any(endereco_payload.values()):
        tomador_payload["endereco"] = endereco_payload
    if any(value for value in tomador_payload.values()):
        payload["tomador"] = tomador_payload
    try:
        if should_emit_async(get_clinica_field(consulta.clinica, "municipio_nfse", "")):
            queue_nfse_issue(issue, "Emissão solicitada manualmente.", payload)
            flash('Emissão adicionada à fila.', 'success')
        else:
            process_nfse_issue(issue, payload)
            flash('Emissão iniciada com sucesso.', 'success')
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Falha ao emitir NFS-e manualmente.")
        issue.erro_mensagem = "Não foi possível emitir a nota agora."
        db.session.add(issue)
        db.session.commit()
        queue_nfse_issue(
            issue,
            "Falha ao emitir; reprocessamento manual necessário.",
            payload,
        )
        flash('Não foi possível emitir a nota. Verifique as configurações fiscais.', 'warning')

    return redirect(
        url_for("contabilidade_nfse_preview", orcamento_id=orcamento.id, emissao=1)
        if orcamento
        else url_for(
            'contabilidade_nfse',
            clinica_id=consulta.clinica_id,
            **({origin_param: origin_id} if origin_param else {}),
        )
    )


@bp.route("/contabilidade/nfse/processar_fila", methods=["POST"])
@login_required
def contabilidade_nfse_processar_fila():
    _ensure_accounting_access()
    clinic_id = request.form.get('clinica_id', type=int)
    orcamento_id = request.form.get('orcamento_id', type=int)
    atendimento_id = request.form.get('atendimento_id', type=int)
    origin_param = "orcamento_id" if orcamento_id else ("atendimento_id" if atendimento_id else None)
    origin_id = orcamento_id or atendimento_id
    limit = request.form.get('limit', type=int) or 10
    _, accessible_ids = _accounting_accessible_clinics()
    if clinic_id and clinic_id not in accessible_ids:
        abort(403)

    result = process_nfse_queue(clinica_id=clinic_id, limit=limit)
    if result.processed:
        flash(f'Fila processada: {result.processed} emissão(ões) enviadas.', 'success')
    if result.failed:
        flash(f'{result.failed} emissão(ões) falharam. Verifique os detalhes.', 'warning')

    return redirect(
        url_for(
            'contabilidade_nfse',
            clinica_id=clinic_id,
            **({origin_param: origin_id} if origin_param else {}),
        )
    )


@bp.route("/contabilidade/nfse/<int:issue_id>/reprocessar", methods=["POST"])
@login_required
def contabilidade_nfse_reprocessar(issue_id):
    _ensure_accounting_access()
    issue = NfseIssue.query.get_or_404(issue_id)
    orcamento_id = request.form.get('orcamento_id', type=int)
    atendimento_id = request.form.get('atendimento_id', type=int)
    origin_param = "orcamento_id" if orcamento_id else ("atendimento_id" if atendimento_id else None)
    origin_id = orcamento_id or atendimento_id
    _, accessible_ids = _accounting_accessible_clinics()
    if issue.clinica_id not in accessible_ids:
        abort(403)

    payload = {"issue_id": issue.id, "manual": True}
    try:
        if should_emit_async(get_clinica_field(issue.clinica, "municipio_nfse", "")):
            queue_nfse_issue(issue, "Reprocessamento manual solicitado.", payload)
            flash('Emissão retornou para a fila.', 'success')
        else:
            process_nfse_issue(issue, payload)
            flash('Reprocessamento iniciado.', 'success')
    except Exception as exc:  # noqa: BLE001
        queue_nfse_issue(
            issue,
            "Falha ao reprocessar; retornou para fila.",
            {"erro": str(exc), **payload},
        )
        flash('Falha ao reprocessar. A emissão voltou para fila.', 'warning')

    return redirect(
        url_for(
            'contabilidade_nfse',
            clinica_id=issue.clinica_id,
            **({origin_param: origin_id} if origin_param else {}),
        )
    )


@bp.route("/contabilidade/nfse/<int:issue_id>/contexto", methods=["POST"])
@login_required
def contabilidade_nfse_contexto(issue_id):
    _ensure_accounting_access()
    issue = NfseIssue.query.get_or_404(issue_id)
    orcamento_id = request.form.get('orcamento_id', type=int)
    atendimento_id = request.form.get('atendimento_id', type=int)
    origin_param = "orcamento_id" if orcamento_id else ("atendimento_id" if atendimento_id else None)
    origin_id = orcamento_id or atendimento_id
    _, accessible_ids = _accounting_accessible_clinics()
    if issue.clinica_id not in accessible_ids:
        abort(403)

    payload = dict(issue.tomador_payload)
    updates = {
        "tutor_nome": (request.form.get("tutor_nome") or "").strip() or None,
        "tutor_documento": (request.form.get("tutor_documento") or "").strip() or None,
        "animal_nome": (request.form.get("animal_nome") or "").strip() or None,
    }
    payload.update(updates)
    issue.tomador = json.dumps(payload, ensure_ascii=False)
    issue.updated_at = utcnow()
    db.session.add(issue)
    db.session.commit()
    flash("Dados atualizados para esta emissão.", "success")

    return redirect(
        url_for(
            'contabilidade_nfse',
            clinica_id=issue.clinica_id,
            **({origin_param: origin_id} if origin_param else {}),
        )
    )


@bp.route("/contabilidade/nfse/<int:issue_id>/cancelar", methods=["POST"])
@login_required
def contabilidade_nfse_cancelar(issue_id):
    _ensure_accounting_access()
    issue = NfseIssue.query.get_or_404(issue_id)
    orcamento_id = request.form.get('orcamento_id', type=int)
    atendimento_id = request.form.get('atendimento_id', type=int)
    origin_param = "orcamento_id" if orcamento_id else ("atendimento_id" if atendimento_id else None)
    origin_id = orcamento_id or atendimento_id
    _, accessible_ids = _accounting_accessible_clinics()
    if issue.clinica_id not in accessible_ids:
        abort(403)

    reason_code = request.form.get('reason_code')
    reason_description = request.form.get('reason_description')
    rules = get_nfse_cancel_rules(get_clinica_field(issue.clinica, "municipio_nfse", ""))
    errors = validate_nfse_cancel_request(
        issue,
        rules,
        reason_code,
        reason_description,
        substituicao=False,
        substituida_por_nfse=None,
    )
    if errors:
        flash(" ".join(errors), 'warning')
        return redirect(
            url_for(
                'contabilidade_nfse',
                clinica_id=issue.clinica_id,
                **({origin_param: origin_id} if origin_param else {}),
            )
        )

    payload = {
        "issue_id": issue.id,
        "reason_code": reason_code,
        "reason_description": reason_description,
    }
    try:
        request_nfse_cancel(issue, reason_code, reason_description, payload)
        flash('Cancelamento solicitado.', 'success')
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception('Erro ao solicitar cancelamento NFS-e', exc_info=exc)
        flash('Erro ao solicitar cancelamento. Tente novamente.', 'danger')

    return redirect(
        url_for(
            'contabilidade_nfse',
            clinica_id=issue.clinica_id,
            **({origin_param: origin_id} if origin_param else {}),
        )
    )


@bp.route("/contabilidade/nfse/<int:issue_id>/substituir", methods=["POST"])
@login_required
def contabilidade_nfse_substituir(issue_id):
    _ensure_accounting_access()
    issue = NfseIssue.query.get_or_404(issue_id)
    orcamento_id = request.form.get('orcamento_id', type=int)
    atendimento_id = request.form.get('atendimento_id', type=int)
    origin_param = "orcamento_id" if orcamento_id else ("atendimento_id" if atendimento_id else None)
    origin_id = orcamento_id or atendimento_id
    _, accessible_ids = _accounting_accessible_clinics()
    if issue.clinica_id not in accessible_ids:
        abort(403)

    reason_code = request.form.get('reason_code')
    reason_description = request.form.get('reason_description')
    substituida_por_nfse = request.form.get('substituida_por_nfse')
    rules = get_nfse_cancel_rules(get_clinica_field(issue.clinica, "municipio_nfse", ""))
    errors = validate_nfse_cancel_request(
        issue,
        rules,
        reason_code,
        reason_description,
        substituicao=True,
        substituida_por_nfse=substituida_por_nfse,
    )
    if errors:
        flash(" ".join(errors), 'warning')
        return redirect(
            url_for(
                'contabilidade_nfse',
                clinica_id=issue.clinica_id,
                **({origin_param: origin_id} if origin_param else {}),
            )
        )

    payload = {
        "issue_id": issue.id,
        "reason_code": reason_code,
        "reason_description": reason_description,
        "substituida_por_nfse": substituida_por_nfse,
    }
    try:
        request_nfse_substitution(
            issue,
            reason_code,
            reason_description,
            substituida_por_nfse,
            payload,
        )
        flash('Substituição solicitada.', 'success')
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception('Erro ao solicitar substituição NFS-e', exc_info=exc)
        flash('Erro ao solicitar substituição. Tente novamente.', 'danger')

    return redirect(
        url_for(
            'contabilidade_nfse',
            clinica_id=issue.clinica_id,
            **({origin_param: origin_id} if origin_param else {}),
        )
    )


@bp.route("/contabilidade/nfse/<int:issue_id>/download/<string:kind>", methods=["GET"])
@login_required
def contabilidade_nfse_download(issue_id, kind):
    _ensure_accounting_access()
    issue = NfseIssue.query.get_or_404(issue_id)
    _, accessible_ids = _accounting_accessible_clinics()
    if issue.clinica_id not in accessible_ids:
        abort(403)

    kind = kind.lower()
    if kind == "xml":
        xml_record = (
            NfseXml.query
            .filter_by(nfse_issue_id=issue.id)
            .order_by(NfseXml.created_at.desc())
            .first()
        )
        xml_content = xml_record.xml if xml_record else (issue.xml_retorno or issue.xml_envio)
        if not xml_content:
            abort(404)
        try:
            if xml_record:
                xml_content = xml_record.get_xml_plaintext()
            else:
                xml_content = decrypt_text_for_clinic(issue.clinica_id, xml_content)
        except MissingMasterKeyError:
            current_app.logger.error(
                "FISCAL_MASTER_KEY ausente; não foi possível descriptografar XML da NFS-e %s.",
                issue.id,
            )
            abort(500)
        response = make_response(xml_content)
        response.headers["Content-Type"] = "application/xml"
        response.headers["Content-Disposition"] = f"attachment; filename=nfse-{issue.id}.xml"
        return response
    if kind == "pdf":
        pdf_record = (
            NfseXml.query
            .filter(NfseXml.nfse_issue_id == issue.id)
            .filter(NfseXml.tipo.ilike("%pdf%"))
            .order_by(NfseXml.created_at.desc())
            .first()
        )
        if not pdf_record:
            abort(404)
        response = make_response(pdf_record.xml)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f"attachment; filename=nfse-{issue.id}.pdf"
        return response

    abort(404)

