import os, sys
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import app as app_module
from app import app as flask_app, db
from models import (
    User,
    Animal,
    Consulta,
    OrcamentoItem,
    BlocoOrcamento,
    Clinica,
    Veterinario,
    Orcamento,
)


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def _bootstrap_consulta(app):
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
        db.session.commit()
        consulta = Consulta(
            animal=animal,
            created_by=vet.id,
            status='in_progress',
            clinica_id=clinica.id,
        )
        orcamento = Orcamento(clinica=clinica, consulta=consulta, descricao='Orçamento teste')
        item = OrcamentoItem(
            consulta=consulta,
            orcamento=orcamento,
            descricao='Consulta',
            valor=50,
            clinica=clinica,
        )
        db.session.add_all([consulta, orcamento, item])
        db.session.commit()
        return consulta.id


def _teardown_db(app):
    with app.app_context():
        db.drop_all()


def test_pagar_bloco_orcamento(app, monkeypatch):
    consulta_id = _bootstrap_consulta(app)
    client = app.test_client()
    captured = {}

    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.post(f'/consulta/{consulta_id}/bloco_orcamento', headers={'Accept': 'application/json'})
        assert resp.status_code == 200
        with app.app_context():
            bloco = BlocoOrcamento.query.first()
            bloco_id = bloco.id

        class FakePrefService:
            def create(self, data):
                captured['preference'] = data
                return {'status': 201, 'response': {'init_point': 'http://mp'}}

        class FakeSDK:
            def preference(self):
                return FakePrefService()

        monkeypatch.setattr(app_module, 'mp_sdk', lambda: FakeSDK())
        resp = client.post(f'/pagar_orcamento/{bloco_id}', headers={'Accept': 'application/json'})
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['success']
        assert payload['redirect_url'] == 'http://mp'
        assert 'auto_return' not in captured['preference']

    _teardown_db(app)


def test_gerar_pagamento_orcamento(app, monkeypatch):
    _bootstrap_consulta(app)
    client = app.test_client()
    captured = {}

    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        with app.app_context():
            orcamento = Orcamento.query.first()
            orcamento_id = orcamento.id

        class FakePrefService:
            def create(self, data):
                captured['preference'] = data
                return {'status': 201, 'response': {'init_point': 'http://mp', 'id': 'pref-1'}}

        class FakeSDK:
            def preference(self):
                return FakePrefService()

        monkeypatch.setattr(app_module, 'mp_sdk', lambda: FakeSDK())
        resp = client.post(f'/orcamento/{orcamento_id}/pagar', headers={'Accept': 'application/json'})
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['success']
        assert payload['payment_link'] == 'http://mp'
        assert payload['payment_status'] == 'pending'
        assert payload['status'] == 'sent'
        assert captured['preference']['external_reference'] == f'orcamento-{orcamento_id}'

        with app.app_context():
            orc = Orcamento.query.get(orcamento_id)
            assert orc.payment_link == 'http://mp'
            assert orc.status == 'sent'

    _teardown_db(app)
