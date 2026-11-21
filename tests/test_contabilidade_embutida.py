"""Contabilidade embutida (2 em 1): despesas no resultado, fechamento e contador."""

import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal

import pytest

from extensions import db
from models import (
    AccountingAccount,
    AccountingDelivery,
    ClassifiedTransaction,
    Clinica,
    Orcamento,
    OrcamentoItem,
    User,
)
from services.finance import (
    build_cash_flow_report,
    build_dre_report,
    calculate_clinic_taxes,
    export_accountant_xlsx,
    register_account,
)

# Mês fixo: o resultado não pode depender do horário em que a suíte roda.
MES = date(2026, 4, 1)
DIA = date(2026, 4, 10)


def _clinic(nome='Clínica Dois em Um'):
    clinic = Clinica(nome=nome)
    db.session.add(clinic)
    db.session.commit()
    return clinic


def _receita(clinic, valor='1000.00'):
    from datetime import datetime
    orcamento = Orcamento(clinica_id=clinic.id, descricao='Atendimentos', created_at=datetime(2026, 4, 10, 12, 0))
    db.session.add(orcamento)
    db.session.flush()
    db.session.add(OrcamentoItem(orcamento_id=orcamento.id, descricao='Consulta',
                                 valor=Decimal(valor), clinica_id=clinic.id))
    db.session.commit()


def _dre(clinic):
    return build_dre_report(clinic.id, MES)['rows'][0]


# ------------------------------------------------- despesas no resultado


def test_despesa_paga_entra_na_dre_e_no_fluxo(app):
    clinic = _clinic()
    _receita(clinic)
    assert _dre(clinic)['despesas_fixas'] == Decimal('0.00')

    register_account(clinic.id, 'payable', 'Aluguel', '400', DIA,
                     category='aluguel', paid_at=DIA)

    row = _dre(clinic)
    assert row['despesas_fixas'] == Decimal('400.00')
    assert row['resultado_liquido'] == row['lucro_bruto'] - Decimal('400.00')
    assert build_cash_flow_report(clinic.id, MES)['realizado']['saidas'] == Decimal('400.00')


def test_conta_em_aberto_nao_entra_ate_a_baixa_e_reabrir_tira(app):
    clinic = _clinic()
    conta = register_account(clinic.id, 'payable', 'Internet', '120', DIA, category='contas_consumo')
    assert _dre(clinic)['despesas_fixas'] == Decimal('0.00')

    conta.mark_paid(DIA)
    db.session.commit()
    assert _dre(clinic)['despesas_fixas'] == Decimal('120.00')

    conta.reopen()
    db.session.commit()
    assert _dre(clinic)['despesas_fixas'] == Decimal('0.00')
    assert ClassifiedTransaction.query.filter_by(origin='account_payable').count() == 0


def test_categorias_vao_para_o_lugar_certo(app):
    clinic = _clinic()
    _receita(clinic, '5000.00')
    hoje = DIA
    register_account(clinic.id, 'payable', 'Salários', '1000', hoje, category='folha', paid_at=hoje)
    register_account(clinic.id, 'payable', 'Ração para revenda', '300', hoje, category='revenda', paid_at=hoje)
    register_account(clinic.id, 'payable', 'DAS', '200', hoje, category='impostos', paid_at=hoje)

    row = _dre(clinic)
    assert row['despesas_fixas'] == Decimal('1000.00')  # folha
    assert row['custos_produtos'] == Decimal('300.00')  # revenda
    # Guia de imposto paga não duplica o imposto estimado da DRE, mas sai do caixa.
    assert build_cash_flow_report(clinic.id, MES)['realizado']['saidas'] == Decimal('1500.00')
    # Folha entra no Fator R.
    assert calculate_clinic_taxes(clinic.id, MES).fator_r > 0


def test_repetir_cria_as_proximas_parcelas_em_aberto(app):
    clinic = _clinic()
    register_account(clinic.id, 'payable', 'Aluguel', '900', DIA,
                     category='aluguel', paid_at=DIA, repeat_months=11)
    contas = AccountingAccount.query.order_by(AccountingAccount.due_date).all()
    assert len(contas) == 12
    assert contas[0].status == 'paid'
    assert all(c.status == 'open' for c in contas[1:])
    assert contas[-1].due_date == date(2027, 3, 10)


def test_planilha_do_contador_traz_o_livro_de_lancamentos(app):
    clinic = _clinic()
    _receita(clinic, '250.00')
    register_account(clinic.id, 'payable', 'Vacinas', '80', DIA, category='insumos', paid_at=DIA)

    content = export_accountant_xlsx(clinic.id, MES)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        workbook = zf.read('xl/workbook.xml').decode('utf-8')
        assert 'Lancamentos' in workbook
        sheets = ''.join(zf.read(n).decode('utf-8') for n in zf.namelist() if n.startswith('xl/worksheets/'))
    assert 'Vacinas' in sheets
    assert 'Conta paga' in sheets
    assert 'Medicamentos, vacinas e materiais' in sheets


# ----------------------------------------------------------- telas e acesso


def _owner(clinic, email):
    from helpers import grant_veterinarian_role

    user = User(name='Dona', email=email)
    user.set_password('x')
    db.session.add(user)
    db.session.flush()
    clinic.owner_id = user.id
    grant_veterinarian_role(user, crmv=f'9{user.id}', clinica=clinic)
    user.clinica_id = clinic.id
    db.session.commit()
    return user


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_lancar_dar_baixa_e_excluir_pela_tela(app, client):
    clinic = _clinic()
    owner = _owner(clinic, 'dona@clinica.com.br')
    _login(client, owner.id)

    resp = client.post(f'/contabilidade/contas?clinica_id={clinic.id}', data={
        'kind': 'payable', 'category': 'aluguel', 'description': 'Aluguel sala',
        'amount': '1500.00', 'due_date': date.today().isoformat(),
    })
    assert resp.status_code == 302
    conta = AccountingAccount.query.one()
    assert conta.category == 'aluguel' and conta.status == 'open'

    client.post(f'/contabilidade/contas/{conta.id}/baixa', data={})
    assert db.session.get(AccountingAccount, conta.id).status == 'paid'

    client.post(f'/contabilidade/contas/{conta.id}/excluir', data={})
    assert AccountingAccount.query.count() == 0


def test_dono_de_outra_clinica_nao_mexe_nas_contas(app, client):
    clinic = _clinic('Clínica A')
    _owner(clinic, 'a@clinica.com.br')
    conta = register_account(clinic.id, 'payable', 'Aluguel A', '100', date.today())
    other = _clinic('Clínica B')
    intrusa = _owner(other, 'b@clinica.com.br')
    _login(client, intrusa.id)

    # 403 vira 404 de propósito (não revela que o registro existe).
    for acao in ('baixa', 'reabrir', 'excluir'):
        assert client.post(f'/contabilidade/contas/{conta.id}/{acao}').status_code in (403, 404)
    assert db.session.get(AccountingAccount, conta.id).status == 'open'
    assert client.post('/contabilidade/contador', data={
        'clinica_id': clinic.id, 'contador_email': 'x@y.com.br'}).status_code in (403, 404)


def test_conta_de_nfse_nao_pode_ser_excluida(app, client):
    clinic = _clinic()
    owner = _owner(clinic, 'nf@clinica.com.br')
    conta = register_account(clinic.id, 'receivable', 'NFS-e 10', '300', date.today(), source_type='nfse')
    _login(client, owner.id)
    client.post(f'/contabilidade/contas/{conta.id}/excluir')
    assert db.session.get(AccountingAccount, conta.id) is not None


def test_painel_do_mes_mostra_resultado_e_checklist(app, client):
    clinic = _clinic()
    owner = _owner(clinic, 'painel@clinica.com.br')
    _receita(clinic, '2000.00')
    register_account(clinic.id, 'payable', 'Aluguel', '500', DIA, category='aluguel', paid_at=DIA)
    _login(client, owner.id)

    html = client.get(f'/contabilidade?clinica_id={clinic.id}&mes=2026-04').get_data(as_text=True)
    assert 'R$ 2.000,00' in html          # faturamento
    assert 'R$ 500,00' in html            # despesas pagas
    assert 'Fechamento de' in html
    assert 'Seu contador' in html
    assert 'Despesas do mês lançadas' in html


# ------------------------------------------------------- envio ao contador


@pytest.fixture
def sent_mail(app, monkeypatch):
    enviados = []
    app.config['MAIL_DEFAULT_SENDER'] = ('PetOrlândia', 'nao-responda@petorlandia.com.br')
    monkeypatch.setattr('services.accounting_close.mail.send', lambda msg: enviados.append(msg))
    return enviados


def test_envio_do_fechamento_ao_contador(app, client, sent_mail):
    clinic = _clinic()
    owner = _owner(clinic, 'envio@clinica.com.br')
    _receita(clinic, '700.00')
    _login(client, owner.id)

    resp = client.post('/contabilidade/fechamento/enviar', data={'clinica_id': clinic.id})
    assert resp.status_code == 302 and sent_mail == []  # sem contador cadastrado

    client.post('/contabilidade/contador', data={
        'clinica_id': clinic.id, 'contador_nome': 'Contabilidade Silva',
        'contador_email': 'Silva@Contabil.com.br', 'envio_automatico': '1',
    })
    client.post('/contabilidade/fechamento/enviar', data={'clinica_id': clinic.id, 'mes': MES.strftime('%Y-%m')})

    assert len(sent_mail) == 1
    msg = sent_mail[0]
    assert msg.recipients == ['silva@contabil.com.br']
    assert 'R$ 700,00' in msg.body
    assert msg.attachments and msg.attachments[0].filename.endswith('.xlsx')
    delivery = AccountingDelivery.query.one()
    assert delivery.month == MES and delivery.automatic is False and delivery.sent_by_id == owner.id

    html = client.get(f'/contabilidade?clinica_id={clinic.id}&mes=2026-04').get_data(as_text=True)
    assert 'Enviado para silva@contabil.com.br' in html


def test_envio_automatico_so_no_dia_5_e_uma_vez(app, sent_mail):
    from services.accounting_close import save_settings, send_monthly_closings

    clinic = _clinic()
    save_settings(clinic.id, nome='Contador', email='contador@exemplo.com.br', automatico=True)
    sem_auto = _clinic('Manual')
    save_settings(sem_auto.id, nome='Outro', email='outro@exemplo.com.br', automatico=False)

    dia5 = date(2026, 12, 5)
    assert send_monthly_closings(dia5 - timedelta(days=1)) == 0
    assert send_monthly_closings(dia5) == 1
    assert send_monthly_closings(dia5) == 0  # não repete
    delivery = AccountingDelivery.query.one()
    assert delivery.clinic_id == clinic.id and delivery.month == date(2026, 11, 1) and delivery.automatic


def test_contador_com_email_invalido_nao_salva(app, client):
    clinic = _clinic()
    owner = _owner(clinic, 'inv@clinica.com.br')
    _login(client, owner.id)
    client.post('/contabilidade/contador', data={'clinica_id': clinic.id, 'contador_email': 'nao é email'})
    from services.accounting_close import get_settings
    assert get_settings(clinic.id) is None


def test_imposto_estimado_nao_conta_o_iss_duas_vezes_no_simples(app):
    clinic = _clinic()
    clinic.aliquota_iss = Decimal('5.00')
    db.session.commit()
    _receita(clinic, '1000.00')
    assert _dre(clinic)['impostos'] == Decimal('60.00')
    taxes = calculate_clinic_taxes(clinic.id, MES)
    assert taxes.iss_total == Decimal('50.00')  # informativo
    assert taxes.das_total == Decimal('60.00')  # 6% (1ª faixa do Anexo III)
    assert _dre(clinic)['impostos'] == Decimal('60.00')


def test_fora_do_simples_vale_o_iss(app):
    clinic = _clinic()
    clinic.aliquota_iss = Decimal('5.00')
    clinic.regime_tributario = 'lucro_presumido'
    db.session.commit()
    _receita(clinic, '1000.00')
    assert _dre(clinic)['impostos'] == Decimal('50.00')

    from services.finance import generate_clinic_notifications
    titles = {n.title for n in generate_clinic_notifications(clinic.id, MES)}
    assert 'ISS do mês pendente' in titles
