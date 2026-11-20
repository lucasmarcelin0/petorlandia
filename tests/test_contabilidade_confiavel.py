"""Regressões da apuração financeira e do isolamento do financeiro por clínica.

Cada teste trava uma falha que já existiu em produção: números inflados ou
divergentes na mesma tela minam a confiança do dono da clínica, e o
financeiro de uma clínica nunca pode aparecer para quem só atende nela.
"""

from decimal import Decimal

from extensions import db
from models import (
    ClassifiedTransaction,
    Clinica,
    Orcamento,
    OrcamentoItem,
    Order,
    OrderItem,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Product,
    User,
)
from services.finance import build_accounting_dashboard, generate_financial_snapshot
from time_utils import now_in_brazil


def _clinic(nome='Clínica Confiável'):
    clinic = Clinica(nome=nome)
    db.session.add(clinic)
    db.session.commit()
    return clinic


def _budget(clinic, valor='100.00', **kwargs):
    orcamento = Orcamento(clinica_id=clinic.id, descricao='Atendimento', **kwargs)
    db.session.add(orcamento)
    db.session.flush()
    item = OrcamentoItem(
        orcamento_id=orcamento.id,
        descricao='Consulta',
        valor=Decimal(valor),
        clinica_id=clinic.id,
    )
    db.session.add(item)
    db.session.commit()
    return orcamento, item


def _revenue(clinic):
    return build_accounting_dashboard(clinic.id)['faturamento_mes']


def test_orcamento_pago_por_link_conta_uma_vez(app):
    import app as app_module

    clinic = _clinic()
    orcamento, _item = _budget(clinic)
    assert _revenue(clinic) == Decimal('100.00')

    orcamento.payment_status = 'paid'
    orcamento.paid_at = now_in_brazil()
    orcamento.status = 'approved'
    app_module._sync_orcamento_payment_classification(orcamento)
    db.session.commit()

    assert _revenue(clinic) == Decimal('100.00')
    # O card do painel (snapshot) mostra o mesmo número do restante da tela.
    assert generate_financial_snapshot(clinic.id).total_receitas_gerais == Decimal('100.00')


def test_orcamento_recusado_ou_cancelado_nao_e_receita(app):
    clinic = _clinic()
    orcamento, _item = _budget(clinic, valor='300.00')
    assert _revenue(clinic) == Decimal('300.00')

    for status in ('rejected', 'canceled'):
        orcamento.status = status
        db.session.commit()
        assert _revenue(clinic) == Decimal('0.00'), status


def test_item_apagado_sai_do_faturamento(app):
    clinic = _clinic()
    _orcamento, item = _budget(clinic, valor='80.00')
    assert _revenue(clinic) == Decimal('80.00')

    db.session.delete(item)
    db.session.commit()

    assert _revenue(clinic) == Decimal('0.00')
    assert ClassifiedTransaction.query.filter_by(origin='service').count() == 0


def test_loja_conta_so_venda_paga_da_propria_clinica(app):
    clinic = _clinic()
    other = _clinic('Outra Loja')
    # Funcionário da clínica comprando para si, de outro vendedor.
    staff = User(name='Funcionária', email='func@clinica.com.br', clinica_id=clinic.id)
    staff.set_password('x')
    tutor = User(name='Tutor', email='tutor@clinica.com.br')
    tutor.set_password('x')
    db.session.add_all([staff, tutor])
    db.session.flush()

    alheio = Product(name='Ração de outra loja', price=Decimal('50'), clinica_id=other.id)
    proprio = Product(name='Shampoo', price=Decimal('40'), clinica_id=clinic.id)
    db.session.add_all([alheio, proprio])
    db.session.flush()

    compra_alheia = Order(user_id=staff.id)
    db.session.add(compra_alheia)
    db.session.flush()
    db.session.add(OrderItem(
        order_id=compra_alheia.id, product_id=alheio.id, item_name='Ração', quantity=2,
        unit_price=Decimal('55'), seller_type='clinica', seller_id=other.id,
    ))
    db.session.add(Payment(
        order_id=compra_alheia.id, user_id=staff.id,
        method=list(PaymentMethod)[0], status=PaymentStatus.COMPLETED,
    ))

    venda = Order(user_id=tutor.id)
    db.session.add(venda)
    db.session.flush()
    db.session.add(OrderItem(
        order_id=venda.id, product_id=proprio.id, item_name='Shampoo', quantity=2,
        unit_price=Decimal('45'), seller_unit_amount=Decimal('40'),
        seller_type='clinica', seller_id=clinic.id,
    ))
    db.session.commit()

    # Carrinho aberto não é venda.
    assert _revenue(clinic) == Decimal('0.00')

    db.session.add(Payment(
        order_id=venda.id, user_id=tutor.id,
        method=list(PaymentMethod)[0], status=PaymentStatus.COMPLETED,
    ))
    db.session.commit()

    # Entra o que a clínica recebe (sem a taxa da plataforma).
    assert _revenue(clinic) == Decimal('80.00')
    assert generate_financial_snapshot(clinic.id).total_receitas_produtos == Decimal('80.00')


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_veterinario_associado_nao_ve_financeiro_de_clinica_alheia(app, client):
    from helpers import grant_veterinarian_role

    propria = _clinic('Clínica Própria')
    alheia = _clinic('Clínica Alheia Sigilosa')
    _budget(alheia, valor='9999.00')

    vet_user = User(name='Dra. Associada', email='associada@clinica.com.br')
    vet_user.set_password('x')
    db.session.add(vet_user)
    db.session.flush()
    propria.owner_id = vet_user.id
    vet = grant_veterinarian_role(vet_user, crmv='99999', clinica=propria)
    vet.clinicas.append(alheia)
    db.session.commit()

    _login(client, vet_user.id)

    response = client.get(f'/contabilidade/financeiro?clinica_id={alheia.id}')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Clínica Alheia Sigilosa' not in html
    assert '9.999,00' not in html
    assert 'Clínica Própria' in html

    export = client.get(f'/contabilidade/exportar/xlsx?clinica_id={alheia.id}')
    assert f'relatorio-contabil-{alheia.id}-' not in export.headers.get('Content-Disposition', '')


def test_painel_mostra_receita_de_hoje_e_como_foi_calculada(app, client):
    from helpers import grant_veterinarian_role

    clinic = _clinic('Clínica do Dia')
    owner = User(name='Dono', email='dono@clinica.com.br')
    owner.set_password('x')
    db.session.add(owner)
    db.session.flush()
    clinic.owner_id = owner.id
    grant_veterinarian_role(owner, crmv='12345', clinica=clinic)
    db.session.commit()
    _budget(clinic, valor='250.00')

    _login(client, owner.id)
    html = client.get(f'/contabilidade/financeiro?clinica_id={clinic.id}').get_data(as_text=True)

    # Sem esperar o job noturno: o lançamento de hoje já aparece no card.
    assert 'R$ 250,00' in html
    assert 'atualizado em' in html
    assert 'Como chegamos a estes números' in html
    assert 'Ticket médio' in html and 'Ticket medio' not in html


def test_conta_manual_recusa_valor_invalido(app):
    import pytest
    from datetime import date

    from models import AccountingAccount
    from services.finance import register_account

    clinic = _clinic()
    for invalido in ('NaN', 'Infinity', '-50', '0'):
        with pytest.raises(ValueError):
            register_account(clinic.id, 'payable', 'Aluguel', invalido, date.today())
    assert AccountingAccount.query.count() == 0

    conta = register_account(clinic.id, 'payable', 'Aluguel', '1500.5', date.today())
    assert conta.net_amount == Decimal('1500.50')
