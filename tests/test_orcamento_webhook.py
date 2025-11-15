import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import app as app_module
from app import app as flask_app, db
from decimal import Decimal
from datetime import datetime, date

from models import (
    Clinica,
    Orcamento,
    OrcamentoItem,
    User,
    Animal,
    Consulta,
    Veterinario,
    ClassifiedTransaction,
)


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        MERCADOPAGO_WEBHOOK_SECRET="test",
    )
    yield flask_app


def _create_orcamento(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinica = Clinica(nome='Clinica 1')
        vet_user = User(name='Vet', email='vet@example.com', worker='veterinario', role='admin')
        vet_user.set_password('x')
        vet_profile = Veterinario(user=vet_user, clinica=clinica, crmv='123')
        tutor = User(name='Tutor', email='tutor@example.com')
        tutor.set_password('y')
        animal = Animal(name='Rex', owner=tutor, clinica=clinica)
        db.session.add_all([clinica, vet_user, vet_profile, tutor, animal])
        db.session.flush()
        consulta = Consulta(animal=animal, created_by=vet_user.id, status='in_progress', clinica=clinica)
        orcamento = Orcamento(clinica=clinica, consulta=consulta, descricao='Teste webhook')
        item = OrcamentoItem(orcamento=orcamento, consulta=consulta, descricao='Consulta', valor=50, clinica=clinica)
        db.session.add_all([consulta, orcamento, item])
        db.session.commit()
        return orcamento.id


def _mock_payment(monkeypatch, payload):
    class FakePayment:
        def get(self, mp_id):
            return {'status': 200, 'response': payload}

    class FakeSDK:
        def payment(self):
            return FakePayment()

    monkeypatch.setattr(app_module, 'mp_sdk', lambda: FakeSDK())


def _post_notification(client):
    return client.post(
        '/notificacoes?type=payment&data.id=999',
        json={'data': {'id': '999'}},
        headers={
            'X-Signature': 'ts=1,v1=' + '0' * 64,
            'x-request-id': 'test-request',
        },
    )


def test_webhook_marks_orcamento_paid(app, monkeypatch):
    orcamento_id = _create_orcamento(app)
    monkeypatch.setattr(app_module, 'verify_mp_signature', lambda req, secret: True)
    payload = {
        'status': 'approved',
        'external_reference': f'orcamento-{orcamento_id}',
        'date_approved': '2024-04-01T12:00:00Z',
    }
    _mock_payment(monkeypatch, payload)
    client = app.test_client()

    resp = _post_notification(client)
    assert resp.status_code == 200

    with app.app_context():
        orcamento = Orcamento.query.get(orcamento_id)
        assert orcamento.payment_status == 'paid'
        assert orcamento.status == 'approved'
        assert orcamento.paid_at is not None


def test_webhook_marks_orcamento_rejected(app, monkeypatch):
    orcamento_id = _create_orcamento(app)
    monkeypatch.setattr(app_module, 'verify_mp_signature', lambda req, secret: True)
    payload = {
        'status': 'rejected',
        'external_reference': f'orcamento-{orcamento_id}',
    }
    _mock_payment(monkeypatch, payload)
    client = app.test_client()

    resp = _post_notification(client)
    assert resp.status_code == 200

    with app.app_context():
        orcamento = Orcamento.query.get(orcamento_id)
        assert orcamento.payment_status == 'failed'
        assert orcamento.status == 'rejected'
        assert orcamento.paid_at is None


def test_orcamento_classification_flow(app, monkeypatch):
    orcamento_id = _create_orcamento(app)
    with app.app_context():
        orcamento = Orcamento.query.get(orcamento_id)
        orcamento.created_at = datetime(2024, 1, 10, 9, 0, 0)
        db.session.add(orcamento)
        db.session.commit()

    client = app.test_client()

    def fake_preference(items, external_reference, back_url):
        return {'payment_url': 'http://mp', 'payment_reference': 'pref-1'}

    monkeypatch.setattr(app_module, '_criar_preferencia_pagamento', fake_preference)

    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.post(
            f'/orcamento/{orcamento_id}/pagar',
            headers={'Accept': 'application/json'},
        )
        assert resp.status_code == 200

    with app.app_context():
        entry = ClassifiedTransaction.query.filter_by(
            origin='orcamento_payment', raw_id=f'orcamento:{orcamento_id}'
        ).one()
        assert entry.category == 'recebivel_orcamento'
        assert entry.value == Decimal('50')
        assert entry.month == date(2024, 1, 1)

    monkeypatch.setattr(app_module, 'verify_mp_signature', lambda req, secret: True)
    payload_paid = {
        'status': 'approved',
        'external_reference': f'orcamento-{orcamento_id}',
        'date_approved': '2024-04-15T10:30:00Z',
    }
    _mock_payment(monkeypatch, payload_paid)
    webhook_client = app.test_client()
    resp = _post_notification(webhook_client)
    assert resp.status_code == 200

    with app.app_context():
        entry = ClassifiedTransaction.query.filter_by(
            origin='orcamento_payment', raw_id=f'orcamento:{orcamento_id}'
        ).one()
        assert entry.category == 'receita_servico'
        assert entry.month == date(2024, 4, 1)
        assert entry.date == datetime(2024, 4, 15, 10, 30)

    payload_failed = {
        'status': 'rejected',
        'external_reference': f'orcamento-{orcamento_id}',
    }
    _mock_payment(monkeypatch, payload_failed)
    resp = _post_notification(webhook_client)
    assert resp.status_code == 200

    with app.app_context():
        remaining = ClassifiedTransaction.query.filter_by(
            origin='orcamento_payment', raw_id=f'orcamento:{orcamento_id}'
        ).count()
        assert remaining == 0
