import os
import sys
from datetime import date, datetime
from decimal import Decimal

import pytest

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db  # noqa: E402
from models import (  # noqa: E402
    ClinicFinancialSnapshot,
    Clinica,
    Orcamento,
    OrcamentoItem,
    Order,
    OrderItem,
    Product,
    User,
)
from services.finance import (  # noqa: E402
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
        )
    )
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
