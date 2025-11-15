import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import app as app_module
from app import app as flask_app, db
from models import User, Animal, Consulta, Orcamento, OrcamentoItem, Clinica, Veterinario


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def _create_orcamento(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinica = Clinica(nome='Clinica 1')
        vet = User(name='Vet', email='vet@example.com', worker='veterinario', role='admin')
        vet.set_password('x')
        vet_v = Veterinario(user=vet, crmv='123', clinica=clinica)
        tutor = User(name='Tutor', email='tutor@example.com')
        tutor.set_password('y')
        animal = Animal(name='Rex', owner=tutor, clinica=clinica)
        db.session.add_all([clinica, vet, vet_v, tutor, animal])
        db.session.flush()
        consulta = Consulta(animal=animal, created_by=vet.id, status='in_progress', clinica_id=clinica.id)
        orcamento = Orcamento(clinica=clinica, consulta=consulta, descricao='Teste webhook')
        item = OrcamentoItem(orcamento=orcamento, descricao='Procedimento', valor=80, clinica=clinica)
        db.session.add_all([consulta, orcamento, item])
        db.session.commit()
        return orcamento.id


def _mock_payment(monkeypatch, payload):
    class FakePaymentAPI:
        def __init__(self, response):
            self._response = response

        def get(self, mp_id):
            return {'status': 200, 'response': self._response}

    class FakeSDK:
        def __init__(self, response):
            self._response = response

        def payment(self):
            return FakePaymentAPI(self._response)

    monkeypatch.setattr(app_module, 'mp_sdk', lambda: FakeSDK(payload))
    monkeypatch.setattr(app_module, 'verify_mp_signature', lambda req, secret: True)


def _post_webhook(client):
    headers = {
        'X-Signature': 'ts=1,v1=' + '0' * 64,
        'x-request-id': 'req-1',
    }
    return client.post('/notificacoes?type=payment&data.id=999', json={'data': {'id': '999'}}, headers=headers)


def test_webhook_sets_orcamento_approved(app, monkeypatch):
    orcamento_id = _create_orcamento(app)
    payload = {
        'status': 'approved',
        'external_reference': f'orcamento-{orcamento_id}',
        'date_approved': '2025-01-01T12:00:00Z',
    }
    _mock_payment(monkeypatch, payload)
    client = app.test_client()
    resp = _post_webhook(client)
    assert resp.status_code == 200
    with app.app_context():
        orcamento = Orcamento.query.get(orcamento_id)
        assert orcamento.status == 'approved'
        assert orcamento.payment_status == 'paid'
        assert orcamento.paid_at is not None
        db.drop_all()


def test_webhook_sets_orcamento_rejected(app, monkeypatch):
    orcamento_id = _create_orcamento(app)
    payload = {
        'status': 'rejected',
        'external_reference': f'orcamento-{orcamento_id}',
    }
    _mock_payment(monkeypatch, payload)
    client = app.test_client()
    resp = _post_webhook(client)
    assert resp.status_code == 200
    with app.app_context():
        orcamento = Orcamento.query.get(orcamento_id)
        assert orcamento.status == 'rejected'
        assert orcamento.payment_status == 'failed'
        assert orcamento.paid_at is None
        db.drop_all()
