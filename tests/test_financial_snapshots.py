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
