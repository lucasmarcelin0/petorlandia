from datetime import datetime, date
from decimal import Decimal
import os
import sys
from uuid import uuid4

import pytest

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as app_module  # noqa: E402
from app import app as flask_app, db  # noqa: E402
from models import (  # noqa: E402
    Animal,
    BlocoOrcamento,
    ClassifiedTransaction,
    Clinica,
    Orcamento,
    OrcamentoItem,
    User,
)


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        LOGIN_DISABLED=True,
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    yield flask_app


def _create_clinic(name="Clínica Teste"):
    clinic = Clinica(nome=name)
    db.session.add(clinic)
    db.session.commit()
    return clinic


def _create_user(clinic):
    user = User(
        name="Tutor",
        email=f"tutor{uuid4().hex}@example.com",
        password_hash="hash",
        clinica_id=clinic.id,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _create_animal(clinic):
    tutor = _create_user(clinic)
    animal = Animal(
        name="Rex",
        user_id=tutor.id,
        clinica_id=clinic.id,
    )
    db.session.add(animal)
    db.session.commit()
    return animal


def _create_orcamento(clinic=None):
    if clinic is None:
        clinic = _create_clinic()
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


def _create_bloco(payment_status="draft"):
    clinic = _create_clinic()
    animal = _create_animal(clinic)
    bloco = BlocoOrcamento(
        animal_id=animal.id,
        clinica_id=clinic.id,
        payment_status=payment_status,
    )
    db.session.add(bloco)
    db.session.commit()
    item = OrcamentoItem(
        bloco_id=bloco.id,
        clinica_id=clinic.id,
        descricao="Banho",
        valor=Decimal("80.00"),
    )
    db.session.add(item)
    db.session.commit()
    db.session.refresh(bloco)
    return bloco


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


def test_sync_bloco_pending_paid_failed_flow(app):
    with app.app_context():
        bloco = _create_bloco(payment_status="pending")

        app_module._sync_orcamento_payment_classification(bloco)
        pending_entry = ClassifiedTransaction.query.filter_by(raw_id=f"bloco_orcamento:{bloco.id}").one()
        assert pending_entry.category == "recebivel_orcamento"
        assert pending_entry.value == Decimal("80.00")

        bloco.payment_status = "paid"
        app_module._sync_orcamento_payment_classification(bloco)
        paid_entry = ClassifiedTransaction.query.filter_by(raw_id=f"bloco_orcamento:{bloco.id}").one()
        assert paid_entry.category == "receita_servico"

        bloco.payment_status = "failed"
        app_module._sync_orcamento_payment_classification(bloco)
        assert (
            ClassifiedTransaction.query.filter_by(raw_id=f"bloco_orcamento:{bloco.id}").count() == 0
        )


def test_pagar_orcamento_route_triggers_sync(app, monkeypatch):
    with app.app_context():
        bloco = _create_bloco(payment_status="draft")

    calls = []
    monkeypatch.setattr(
        app_module,
        "_criar_preferencia_pagamento",
        lambda *args, **kwargs: {
            "payment_url": "https://pagamento.test",
            "payment_reference": "pref-123",
        },
    )
    monkeypatch.setattr(app_module, "_render_orcamento_history", lambda *args, **kwargs: "<html></html>")
    monkeypatch.setattr(app_module, "_sync_orcamento_payment_classification", lambda record: calls.append(record.id))
    monkeypatch.setattr(app_module, "ensure_clinic_access", lambda *args, **kwargs: None)

    with app.test_client() as client:
        response = client.post(
            f"/pagar_orcamento/{bloco.id}",
            headers={"Accept": "application/json"},
        )

    assert response.status_code == 200
    assert calls == [bloco.id]


def test_gerar_link_pagamento_orcamento_triggers_sync(app, monkeypatch):
    with app.app_context():
        clinic = _create_clinic()
        orcamento = _create_orcamento(clinic)

    calls = []
    monkeypatch.setattr(
        app_module,
        "_criar_preferencia_pagamento",
        lambda *args, **kwargs: {
            "payment_url": "https://pagamento.test",
            "payment_reference": "pref-456",
        },
    )
    monkeypatch.setattr(app_module, "_sync_orcamento_payment_classification", lambda record: calls.append(record.id))
    monkeypatch.setattr(app_module, "ensure_clinic_access", lambda *args, **kwargs: None)

    with app.test_client() as client:
        response = client.post(f"/orcamento/{orcamento.id}/pagar")

    assert response.status_code == 200
    assert calls == [orcamento.id]


def test_atualizar_bloco_orcamento_triggers_sync(app, monkeypatch):
    with app.app_context():
        bloco = _create_bloco(payment_status="pending")

    calls = []
    monkeypatch.setattr(app_module, "ensure_clinic_access", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "is_veterinarian", lambda *args, **kwargs: True)
    monkeypatch.setattr(app_module, "_render_orcamento_history", lambda *args, **kwargs: "<html></html>")
    monkeypatch.setattr(app_module, "_sync_orcamento_payment_classification", lambda record: calls.append(record.id))

    payload = {"itens": [{"descricao": "Novo", "valor": 120.0}]}
    with app.test_client() as client:
        response = client.post(
            f"/bloco_orcamento/{bloco.id}/atualizar",
            json=payload,
            headers={"Accept": "application/json"},
        )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert calls == [bloco.id]
