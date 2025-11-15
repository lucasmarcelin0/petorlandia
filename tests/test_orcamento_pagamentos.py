import os
import sys
from decimal import Decimal

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

import app as app_module
from app import app as flask_app, db
from models import (
    Animal,
    Clinica,
    Consulta,
    Orcamento,
    OrcamentoItem,
    User,
    Veterinario,
)

@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        MERCADOPAGO_WEBHOOK_SECRET="",
    )
    yield flask_app


def _criar_orcamento(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinica = Clinica(nome="Clínica Teste")
        vet = User(name="Vet", email="vet@example.com", worker="veterinario", role="admin")
        vet.set_password("x")
        tutor = User(name="Tutor", email="tutor@example.com", phone="5511999999999")
        tutor.set_password("y")
        vet_profile = Veterinario(user=vet, crmv="123", clinica=clinica)
        animal = Animal(name="Rex", owner=tutor, clinica=clinica)
        db.session.add_all([clinica, vet, vet_profile, tutor, animal])
        db.session.commit()
        consulta = Consulta(animal=animal, created_by=vet.id, clinica=clinica, status="in_progress")
        orcamento = Orcamento(clinica=clinica, consulta=consulta, descricao="Tratamento completo")
        item = OrcamentoItem(
            consulta=consulta,
            orcamento=orcamento,
            descricao="Vacina",
            valor=Decimal("80.00"),
            clinica=clinica,
        )
        db.session.add_all([consulta, orcamento, item])
        db.session.commit()
        return orcamento.id


def _mock_payment(monkeypatch, info):
    class FakePaymentService:
        def get(self, mp_id):
            return {"status": 200, "response": info}

    class FakeSDK:
        def payment(self):
            return FakePaymentService()

    monkeypatch.setattr(app_module, "mp_sdk", lambda: FakeSDK())
    monkeypatch.setattr(app_module, "verify_mp_signature", lambda req, secret: True)


def _call_webhook(client, payload):
    return client.post(
        "/notificacoes?type=payment",
        json=payload,
        headers={"x-request-id": "test", "x-signature": "ts=1;v1=abc"},
    )


def test_webhook_marks_orcamento_as_paid(app, monkeypatch):
    orcamento_id = _criar_orcamento(app)
    info = {
        "status": "approved",
        "external_reference": f"orcamento-{orcamento_id}",
        "date_approved": "2024-05-10T12:00:00Z",
    }
    client = app.test_client()
    _mock_payment(monkeypatch, info)
    resp = _call_webhook(client, {"data": {"id": "123"}})
    assert resp.status_code == 200
    with app.app_context():
        orcamento = Orcamento.query.get(orcamento_id)
        assert orcamento.payment_status == "paid"
        assert orcamento.status == "approved"
        assert orcamento.paid_at is not None
        db.drop_all()


def test_webhook_marks_orcamento_as_rejected(app, monkeypatch):
    orcamento_id = _criar_orcamento(app)
    info = {
        "status": "rejected",
        "external_reference": f"orcamento-{orcamento_id}",
        "date_last_updated": "2024-05-10T12:00:00Z",
    }
    client = app.test_client()
    _mock_payment(monkeypatch, info)
    resp = _call_webhook(client, {"data": {"id": "123"}})
    assert resp.status_code == 200
    with app.app_context():
        orcamento = Orcamento.query.get(orcamento_id)
        assert orcamento.payment_status == "failed"
        assert orcamento.status == "rejected"
        assert orcamento.paid_at is None
        db.drop_all()
