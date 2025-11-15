import os
import sys
from datetime import datetime, date
from decimal import Decimal

import pytest

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as app_module  # noqa: E402
from app import app as flask_app, db  # noqa: E402
from models import ClassifiedTransaction, Clinica, Orcamento, OrcamentoItem  # noqa: E402


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


def _create_orcamento(clinic=None):
    if clinic is None:
        clinic = Clinica(nome="Clínica Teste")
        db.session.add(clinic)
        db.session.commit()
    orcamento = Orcamento(
        clinica_id=clinic.id,
        descricao="Procedimentos gerais",
        created_at=datetime(2024, 5, 5, 10, 0, 0),
    )
    db.session.add(orcamento)
    db.session.commit()
    item = OrcamentoItem(
        orcamento_id=orcamento.id,
        clinica_id=clinic.id,
        descricao="Consulta",
        valor=Decimal("150.00"),
    )
    db.session.add(item)
    db.session.commit()
    db.session.refresh(orcamento)
    return orcamento


def test_sync_orcamento_paid_creates_transaction(app):
    with app.app_context():
        orcamento = _create_orcamento()
        orcamento.payment_status = "paid"
        orcamento.paid_at = datetime(2024, 6, 20, 9, 30)

        app_module._sync_orcamento_payment_classification(orcamento)

        record = ClassifiedTransaction.query.filter_by(raw_id=f"orcamento:{orcamento.id}").one()
        assert record.category == "receita_servico"
        assert record.month == date(2024, 6, 1)
        assert record.value == Decimal("150.00")
        assert record.description.startswith("Orçamento #")


def test_sync_orcamento_pending_paid_failed_flow(app):
    with app.app_context():
        orcamento = _create_orcamento()

        orcamento.payment_status = "pending"
        app_module._sync_orcamento_payment_classification(orcamento)
        pending_record = ClassifiedTransaction.query.filter_by(raw_id=f"orcamento:{orcamento.id}").one()
        assert pending_record.category == "recebivel_orcamento"
        assert pending_record.month == date(2024, 5, 1)

        orcamento.payment_status = "paid"
        orcamento.paid_at = datetime(2024, 7, 3, 8, 0)
        app_module._sync_orcamento_payment_classification(orcamento)
        paid_record = ClassifiedTransaction.query.filter_by(raw_id=f"orcamento:{orcamento.id}").one()
        assert paid_record.category == "receita_servico"
        assert paid_record.month == date(2024, 7, 1)

        orcamento.payment_status = "failed"
        orcamento.paid_at = None
        app_module._sync_orcamento_payment_classification(orcamento)
        assert ClassifiedTransaction.query.filter_by(raw_id=f"orcamento:{orcamento.id}").count() == 0
