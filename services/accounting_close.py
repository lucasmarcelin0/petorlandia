"""Fechamento do mês e envio ao contador — a contabilidade embutida.

A clínica não precisa de outro sistema nem de planilha paralela: o que
acontece no atendimento já vira lançamento (``services.finance``); aqui fica a
visão do mês para o dono (resultado, contas, pendências do fechamento) e a
entrega ao contador — por um clique ou sozinha, todo dia 5.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from flask import current_app
from flask_mail import Message as MailMessage
from sqlalchemy import func

from extensions import db, mail
from models import (
    AccountingAccount,
    AccountingDelivery,
    ClinicAccountingSettings,
    Clinica,
    PJPayment,
)
from services.finance import (
    ZERO,
    _normalize_month,
    build_dre_report,
    export_accountant_xlsx,
    pj_payments_schema_is_ready,
)
from template_filters import currency_br
from time_utils import now_in_brazil

XLSX_MIMETYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
#: Dia do mês em que o fechamento do mês anterior sai sozinho para o contador.
AUTO_DELIVERY_DAY = 5


def get_settings(clinic_id: int) -> ClinicAccountingSettings | None:
    return ClinicAccountingSettings.query.filter_by(clinic_id=clinic_id).first()


def save_settings(clinic_id: int, *, nome: str | None, email: str | None, automatico: bool) -> ClinicAccountingSettings:
    settings = get_settings(clinic_id)
    if settings is None:
        settings = ClinicAccountingSettings(clinic_id=clinic_id)
        db.session.add(settings)
    settings.contador_nome = (' '.join((nome or '').split()) or None)
    settings.contador_email = ((email or '').strip().lower() or None)
    settings.envio_automatico = bool(automatico)
    db.session.commit()
    return settings


def _sum_accounts(query) -> Decimal:
    total = query.with_entities(func.coalesce(func.sum(AccountingAccount.net_amount), 0)).scalar()
    return Decimal(str(total or 0))


def month_overview(clinic_id: int, month) -> dict:
    """Resultado do mês, contas e checklist de fechamento."""

    month_start = _normalize_month(month)
    month_end = month_start + relativedelta(months=1)
    dre = build_dre_report(clinic_id, month_start, 'monthly')
    row = dre['rows'][0] if dre['rows'] else {}
    receita = row.get('receita_bruta', ZERO)
    despesas = row.get('despesas_fixas', ZERO) + row.get('custos_produtos', ZERO)
    impostos = row.get('impostos', ZERO)
    resultado = row.get('resultado_liquido', ZERO)

    today = now_in_brazil().date()
    base = AccountingAccount.query.filter(AccountingAccount.clinic_id == clinic_id)
    open_receivable = base.filter(AccountingAccount.kind == 'receivable', AccountingAccount.status == 'open')
    open_payable = base.filter(AccountingAccount.kind == 'payable', AccountingAccount.status == 'open')
    overdue_receivable = open_receivable.filter(AccountingAccount.due_date < today)
    overdue_payable = open_payable.filter(AccountingAccount.due_date < today)
    next_payable = open_payable.filter(
        AccountingAccount.due_date >= today,
        AccountingAccount.due_date <= today + timedelta(days=7),
    )
    paid_expenses = base.filter(
        AccountingAccount.kind == 'payable',
        AccountingAccount.status == 'paid',
        AccountingAccount.paid_at >= month_start,
        AccountingAccount.paid_at < month_end,
    ).count()

    plantoes_sem_nf = 0
    if pj_payments_schema_is_ready():
        plantoes_sem_nf = (
            PJPayment.query
            .filter(PJPayment.clinic_id == clinic_id)
            .filter(PJPayment.data_servico >= month_start, PJPayment.data_servico < month_end)
            .filter(func.coalesce(func.trim(PJPayment.nota_fiscal_numero), '') == '')
            .count()
        )

    delivery = (
        AccountingDelivery.query
        .filter_by(clinic_id=clinic_id, month=month_start)
        .order_by(AccountingDelivery.sent_at.desc())
        .first()
    )
    settings = get_settings(clinic_id)

    overdue_count = overdue_receivable.count() + overdue_payable.count()
    checklist = [
        {
            'key': 'despesas',
            'label': 'Despesas do mês lançadas',
            'done': paid_expenses > 0,
            'hint': 'Aluguel, folha, insumos e outras contas pagas no mês.',
        },
        {
            'key': 'vencidas',
            'label': 'Nenhuma conta vencida em aberto',
            'done': overdue_count == 0,
            'hint': f'{overdue_count} conta(s) vencida(s): dê baixa ou renegocie.' if overdue_count else '',
        },
        {
            'key': 'plantoes',
            'label': 'Plantões e PJs com nota fiscal',
            'done': plantoes_sem_nf == 0,
            'hint': f'{plantoes_sem_nf} pagamento(s) PJ sem número de nota.' if plantoes_sem_nf else '',
        },
        {
            'key': 'contador',
            'label': 'Fechamento enviado ao contador',
            'done': delivery is not None,
            'hint': '' if delivery else (
                'Cadastre o e-mail do contador para enviar.' if not (settings and settings.contador_email) else ''
            ),
        },
    ]
    return {
        'month': month_start,
        'receita': receita,
        'despesas': despesas,
        'impostos': impostos,
        'resultado': resultado,
        'a_receber': _sum_accounts(open_receivable),
        'a_receber_vencido': _sum_accounts(overdue_receivable),
        'a_pagar_7_dias': _sum_accounts(next_payable),
        'a_pagar_vencido': _sum_accounts(overdue_payable),
        'despesas_lancadas': paid_expenses,
        'checklist': checklist,
        'checklist_done': sum(1 for item in checklist if item['done']),
        'delivery': delivery,
        'settings': settings,
    }


def _email_body(clinic: Clinica, overview: dict, settings: ClinicAccountingSettings, *, sent_by=None, automatic=False) -> str:
    saudacao = f'Olá, {settings.contador_nome}!' if settings.contador_nome else 'Olá!'
    referencia = overview['month'].strftime('%m/%Y')
    origem = (
        'automaticamente, como combinado com a clínica'
        if automatic
        else f'por {getattr(sent_by, "name", None) or "um responsável da clínica"}'
    )
    return (
        f'{saudacao}\n\n'
        f'Segue o fechamento de {referencia} da {clinic.nome}, gerado pela PetOrlândia.\n\n'
        'Resumo do mês:\n'
        f'• Faturamento: {currency_br(overview["receita"])}\n'
        f'• Despesas e custos pagos: {currency_br(overview["despesas"])}\n'
        f'• Impostos estimados: {currency_br(overview["impostos"])} (estimativa; a apuração oficial é sua)\n'
        f'• Resultado estimado: {currency_br(overview["resultado"])}\n'
        f'• Contas a receber em aberto: {currency_br(overview["a_receber"])}\n\n'
        'A planilha anexa traz o livro de lançamentos do mês, a DRE, o fluxo de caixa '
        'e as contas a pagar e a receber. As notas fiscais de serviço ficam disponíveis '
        'com a clínica, em Contabilidade → NFS-e.\n\n'
        f'Enviado {origem} pela PetOrlândia. Dúvidas sobre os lançamentos: responda '
        'para a clínica.'
    )


def send_month_to_accountant(clinic: Clinica, month, *, sent_by=None, automatic: bool = False) -> AccountingDelivery | None:
    """Envia o fechamento do mês ao contador. Devolve o registro ou ``None``."""

    settings = get_settings(clinic.id)
    if not settings or not settings.contador_email:
        return None
    if not current_app.config.get('MAIL_DEFAULT_SENDER'):
        current_app.logger.warning('[Contador] E-mail não configurado; fechamento da clínica %s não enviado.', clinic.id)
        return None

    month_start = _normalize_month(month)
    overview = month_overview(clinic.id, month_start)
    content = export_accountant_xlsx(clinic.id, month_start)
    message = MailMessage(
        subject=f"Fechamento {month_start:%m/%Y} — {' '.join((clinic.nome or 'Clínica').split())}",
        recipients=[settings.contador_email],
        body=_email_body(clinic, overview, settings, sent_by=sent_by, automatic=automatic),
    )
    owner_email = (getattr(getattr(clinic, 'owner', None), 'email', '') or '').strip()
    clinic_email = (getattr(clinic, 'email', '') or '').strip()
    reply_to = clinic_email or owner_email
    if reply_to:
        message.reply_to = reply_to
    message.attach(f'fechamento-{month_start:%Y-%m}.xlsx', XLSX_MIMETYPE, content)
    try:
        mail.send(message)
    except Exception:  # noqa: BLE001 - registra e devolve None para a tela avisar
        current_app.logger.exception('[Contador] Falha ao enviar fechamento da clínica %s', clinic.id)
        return None

    delivery = AccountingDelivery(
        clinic_id=clinic.id,
        month=month_start,
        sent_to=settings.contador_email,
        sent_by_id=getattr(sent_by, 'id', None),
        automatic=automatic,
        sent_at=now_in_brazil(),
    )
    db.session.add(delivery)
    db.session.commit()
    return delivery


def send_monthly_closings(today: date | None = None) -> int:
    """Job diário: no dia 5, envia o mês anterior para quem pediu envio automático."""

    today = today or now_in_brazil().date()
    if today.day != AUTO_DELIVERY_DAY:
        return 0
    previous_month = (today.replace(day=1) - relativedelta(months=1))
    sent = 0
    candidates = (
        ClinicAccountingSettings.query
        .filter(ClinicAccountingSettings.envio_automatico.is_(True))
        .filter(ClinicAccountingSettings.contador_email.isnot(None))
        .all()
    )
    for settings in candidates:
        already = AccountingDelivery.query.filter_by(clinic_id=settings.clinic_id, month=previous_month).first()
        if already:
            continue
        clinic = db.session.get(Clinica, settings.clinic_id)
        if clinic is None:
            continue
        if send_month_to_accountant(clinic, previous_month, automatic=True):
            sent += 1
    current_app.logger.info('[Contador] Fechamentos enviados automaticamente: %s', sent)
    return sent
