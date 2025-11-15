import os
import sys
from datetime import date, datetime
from decimal import Decimal

import pytest

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db  # noqa: E402
from models import (  # noqa: E402
    ClassifiedTransaction,
    ClinicFinancialSnapshot,
    ClinicNotification,
    ClinicTaxes,
    Clinica,
    Orcamento,
    OrcamentoItem,
    Order,
    OrderItem,
    PJPayment,
    Product,
    ServicoClinica,
    User,
)
from services.finance import (  # noqa: E402
    calculate_clinic_taxes,
    classify_transactions_for_month,
    generate_clinic_notifications,
    generate_financial_snapshot,
    update_financial_snapshots_daily,
)


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    yield flask_app


def _create_clinic_with_data():
    clinic = Clinica(nome="Clínica Central")
    db.session.add(clinic)

    buyer = User(
        name="Comprador",
        email="comprador@example.com",
        password_hash="hash",
        clinica=clinic,
    )
    db.session.add(buyer)

    product = Product(name="Ração", price=50.0, stock=10)
    db.session.add(product)
    db.session.commit()

    servico = ServicoClinica(descricao="Consulta", valor=Decimal('120.50'), clinica=clinic)
    db.session.add(servico)
    db.session.commit()

    order = Order(user_id=buyer.id, created_at=datetime(2024, 5, 10, 8, 0, 0))
    db.session.add(order)
    db.session.commit()

    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        item_name=product.name,
        quantity=2,
        unit_price=Decimal('50.00'),
    )
    db.session.add(item)

    orcamento = Orcamento(
        clinica_id=clinic.id,
        descricao="Procedimentos de maio",
        created_at=datetime(2024, 5, 5, 9, 0, 0),
    )
    db.session.add(orcamento)
    db.session.commit()

    db.session.add(
        OrcamentoItem(
            orcamento_id=orcamento.id,
            clinica_id=clinic.id,
            descricao="Consulta",
            valor=Decimal('120.50'),
            servico_id=servico.id,
        )
    )
    db.session.commit()

    pj_payment = PJPayment(
        clinic_id=clinic.id,
        prestador_nome="Vet Serviços",
        prestador_cnpj="12.345.678/0001-00",
        nota_fiscal_numero="NF-001",
        valor=Decimal('12000.00'),
        data_servico=date(2024, 5, 12),
        data_pagamento=date(2024, 5, 15),
        status='pago',
    )
    db.session.add(pj_payment)
    db.session.commit()
    return clinic


def test_generate_financial_snapshot_creates_record(app):
    with app.app_context():
        clinic = _create_clinic_with_data()
        snapshot = generate_financial_snapshot(clinic.id, date(2024, 5, 17))

        assert snapshot.month == date(2024, 5, 1)
        assert snapshot.total_receitas_servicos == Decimal('120.50')
        assert snapshot.total_receitas_produtos == Decimal('100.00')
        assert snapshot.total_receitas_gerais == Decimal('220.50')

        stored = ClinicFinancialSnapshot.query.filter_by(clinic_id=clinic.id, month=date(2024, 5, 1)).one()
        assert stored.id == snapshot.id


def test_update_financial_snapshots_daily_handles_zero_data(app):
    with app.app_context():
        clinic = Clinica(nome="Clínica Sem Dados")
        db.session.add(clinic)
        db.session.commit()

        snapshots = update_financial_snapshots_daily(target_month=date(2024, 6, 2))

        assert len(snapshots) == 1
        snap = snapshots[0]
        assert snap.month == date(2024, 6, 1)
        assert snap.total_receitas_servicos == Decimal('0')
        assert snap.total_receitas_produtos == Decimal('0')
        assert snap.total_receitas_gerais == Decimal('0')


def test_classify_transactions_creates_service_and_product_entries(app):
    with app.app_context():
        clinic = _create_clinic_with_data()
        records = classify_transactions_for_month(clinic.id, date(2024, 5, 10))

        assert len(records) == 3
        stored = ClassifiedTransaction.query.order_by(ClassifiedTransaction.category).all()
        assert len(stored) == 3

        service = next(entry for entry in stored if entry.category == "receita_servico")
        assert service.origin == "service"
        assert service.subcategory == "Consulta"
        assert service.month == date(2024, 5, 1)
        assert service.value == Decimal('120.50')

        product = next(entry for entry in stored if entry.category == "receita_produto")
        assert product.origin == "product_sale"
        assert product.subcategory == "others"
        assert product.description == "Ração"
        assert product.month == date(2024, 5, 1)

        pj_payment = next(entry for entry in stored if entry.category == "pagamento_pj")
        assert pj_payment.origin == "vet_payment"
        assert pj_payment.month == date(2024, 5, 1)
        assert pj_payment.value == Decimal('12000.00')


def test_classify_transactions_upserts_existing_rows(app):
    with app.app_context():
        clinic = _create_clinic_with_data()
        classify_transactions_for_month(clinic.id, date(2024, 5, 10))

        # Update original data and re-run classification.
        service_item = OrcamentoItem.query.filter_by(clinica_id=clinic.id).one()
        service_item.valor = Decimal('200.00')
        order_item = OrderItem.query.first()
        order_item.quantity = 3
        db.session.commit()

        classify_transactions_for_month(clinic.id, date(2024, 5, 10))

        entries = ClassifiedTransaction.query.all()
        assert len(entries) == 3

        service_entry = ClassifiedTransaction.query.filter_by(category="receita_servico").one()
        assert service_entry.value == Decimal('200.00')

        product_entry = ClassifiedTransaction.query.filter_by(category="receita_produto").one()
        assert product_entry.value == Decimal('150.00')
        pj_entry = ClassifiedTransaction.query.filter_by(category="pagamento_pj").one()
        assert pj_entry.value == Decimal('12000.00')


def test_calculate_clinic_taxes_creates_record(app):
    with app.app_context():
        clinic = _create_clinic_with_data()
        month = date(2024, 5, 10)
        generate_financial_snapshot(clinic.id, month)

        taxes = ClinicTaxes.query.filter_by(clinic_id=clinic.id, month=date(2024, 5, 1)).one()
        assert taxes.iss_total == Decimal('6.03')
        assert taxes.das_total == Decimal('13.23')
        assert taxes.retencoes_pj == Decimal('600.00')
        assert taxes.faixa_simples == 1
        assert taxes.fator_r == Decimal('54.4218')
        assert taxes.projecao_anual == Decimal('2646.00')


def test_calculate_clinic_taxes_updates_existing_record(app):
    with app.app_context():
        clinic = _create_clinic_with_data()
        month = date(2024, 5, 10)
        generate_financial_snapshot(clinic.id, month)

        service_item = OrcamentoItem.query.filter_by(clinica_id=clinic.id).one()
        service_item.valor = Decimal('300.00')
        order_item = OrderItem.query.first()
        order_item.quantity = 3
        db.session.commit()

        generate_financial_snapshot(clinic.id, month)

        taxes = ClinicTaxes.query.filter_by(clinic_id=clinic.id, month=date(2024, 5, 1)).one()
        assert ClinicTaxes.query.count() == 1
        assert taxes.iss_total == Decimal('15.00')
        assert taxes.das_total == Decimal('27.00')
        assert taxes.retencoes_pj == Decimal('600.00')
        assert taxes.projecao_anual == Decimal('5400.00')


def test_generate_clinic_notifications_detects_key_alerts(app):
    with app.app_context():
        clinic = _create_clinic_with_data()
        month = date(2024, 5, 1)

        payment = PJPayment.query.first()
        payment.nota_fiscal_numero = None

        taxes = ClinicTaxes(
            clinic_id=clinic.id,
            month=month,
            iss_total=Decimal('500.00'),
            das_total=Decimal('800.00'),
            retencoes_pj=Decimal('0'),
            fator_r=Decimal('0.10'),
            faixa_simples=5,
            projecao_anual=Decimal('5000000.00'),
        )
        db.session.add(taxes)

        db.session.add(
            ClassifiedTransaction(
                clinic_id=clinic.id,
                date=datetime(2024, 5, 5, 12, 0),
                month=month,
                origin='manual',
                description='Ajuste negativo',
                value=Decimal('-100.00'),
                category='receita_servico',
                subcategory='ajuste',
                raw_id='adjust-1',
            )
        )
        db.session.commit()

        notifications = generate_clinic_notifications(clinic.id, month)
        titles = {notice.title for notice in notifications}

        assert "Prestador sem nota fiscal" in titles
        assert "Fator R abaixo do limite" in titles
        assert "ISS do mês pendente" in titles
        assert "DAS do mês pendente" in titles
        assert "Receitas negativas ou inconsistentes" in titles
        assert "Projeção anual acima do limite do Simples Nacional" in titles


def test_generate_clinic_notifications_marks_alert_resolved(app):
    with app.app_context():
        clinic = _create_clinic_with_data()
        month = date(2024, 5, 1)

        payment = PJPayment.query.first()
        payment.nota_fiscal_numero = None
        taxes = ClinicTaxes(
            clinic_id=clinic.id,
            month=month,
            iss_total=Decimal('0.00'),
            das_total=Decimal('0.00'),
            retencoes_pj=Decimal('0.00'),
            fator_r=Decimal('0.50'),
            faixa_simples=1,
            projecao_anual=Decimal('100000.00'),
        )
        db.session.add(taxes)
        db.session.commit()

        generate_clinic_notifications(clinic.id, month)
        unpaid_alert = ClinicNotification.query.filter_by(
            clinic_id=clinic.id,
            month=month,
            title="Prestador sem nota fiscal",
        ).one()
        assert unpaid_alert.resolved is False

        payment.nota_fiscal_numero = "NF-OK"
        db.session.commit()

        notifications = generate_clinic_notifications(clinic.id, month)
        assert all(alert.title != "Prestador sem nota fiscal" for alert in notifications)
        resolved_alert = ClinicNotification.query.filter_by(
            clinic_id=clinic.id,
            month=month,
            title="Prestador sem nota fiscal",
        ).one()
        assert resolved_alert.resolved is True


def test_contabilidade_pagamentos_auto_classifies_transactions(app):
    with app.app_context():
        clinic = _create_clinic_with_data()
        clinic_id = clinic.id
        admin = User(name="Admin", email="admin@example.com", role="admin")
        admin.set_password("secret")
        db.session.add(admin)
        db.session.commit()

        assert ClassifiedTransaction.query.count() == 0

    client = app.test_client()
    with client:
        login_response = client.post(
            '/login',
            data={'email': 'admin@example.com', 'password': 'secret'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        month_value = '2024-05'
        response = client.get(
            f'/contabilidade/pagamentos?clinica_id={clinic_id}&mes={month_value}',
            follow_redirects=True,
        )
        assert response.status_code == 200

        with app.app_context():
            entries = ClassifiedTransaction.query.order_by(ClassifiedTransaction.id).all()
            assert len(entries) == 3
            values = sorted(entry.value for entry in entries)
            assert values == [Decimal('100.00'), Decimal('120.50'), Decimal('12000.00')]

            orcamento = Orcamento.query.filter_by(clinica_id=clinic_id).first()
            servico = ServicoClinica.query.filter_by(clinica_id=clinic_id).first()
            db.session.add(
                OrcamentoItem(
                    orcamento_id=orcamento.id,
                    clinica_id=clinic_id,
                    descricao='Retorno detalhado',
                    valor=Decimal('80.00'),
                    servico_id=servico.id,
                )
            )
            db.session.commit()

        second_response = client.get(
            f'/contabilidade/pagamentos?clinica_id={clinic_id}&mes={month_value}',
            follow_redirects=True,
        )
        assert second_response.status_code == 200

        with app.app_context():
            entries = ClassifiedTransaction.query.order_by(ClassifiedTransaction.id).all()
            assert len(entries) == 4
            new_entry = ClassifiedTransaction.query.filter_by(value=Decimal('80.00')).one()
            assert new_entry.description == 'Retorno detalhado'


def test_cli_classify_transactions_history_backfills_data(app):
    with app.app_context():
        clinic = _create_clinic_with_data()
        clinic_id = clinic.id
        assert ClassifiedTransaction.query.count() == 0

    runner = app.test_cli_runner()
    result = runner.invoke(
        args=[
            'classify-transactions-history',
            '--months',
            '1',
            '--clinic-id',
            str(clinic_id),
            '--reference-month',
            '2024-05',
        ],
    )
    assert result.exit_code == 0

    with app.app_context():
        assert ClassifiedTransaction.query.count() == 3
