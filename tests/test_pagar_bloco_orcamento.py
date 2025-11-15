import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import app as app_module
from app import app as flask_app, db
from models import (
    User,
    Animal,
    Consulta,
    Orcamento,
    OrcamentoItem,
    BlocoOrcamento,
    Clinica,
    Veterinario,
)


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_pagar_bloco_orcamento(app, monkeypatch):
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
        consulta = Consulta(animal=animal, created_by=vet.id, status='in_progress', clinica_id=clinica.id)
        item = OrcamentoItem(consulta=consulta, descricao='Consulta', valor=50, clinica=clinica)
        db.session.add_all([consulta, item])
        db.session.commit()
        consulta_id = consulta.id

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.post(f'/consulta/{consulta_id}/bloco_orcamento', headers={'Accept': 'application/json'})
        assert resp.status_code == 200
        with app.app_context():
            bloco = BlocoOrcamento.query.first()
            bloco_id = bloco.id

        class FakePrefService:
            def create(self, data):
                return {'status': 201, 'response': {'init_point': 'http://mp', 'id': 'pref-1'}}

        class FakeSDK:
            def preference(self):
                return FakePrefService()

        monkeypatch.setattr(app_module, 'mp_sdk', lambda: FakeSDK())
        resp = client.post(f'/pagar_orcamento/{bloco_id}', headers={'Accept': 'application/json'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success']
        assert data['redirect_url'] == 'http://mp'

    with app.app_context():
        bloco = BlocoOrcamento.query.first()
        assert bloco.payment_link == 'http://mp'
        assert bloco.payment_status == 'pending'
        db.drop_all()


def test_gerar_pagamento_orcamento(app, monkeypatch):
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
        orcamento = Orcamento(clinica=clinica, consulta=consulta, descricao='Teste')
        item = OrcamentoItem(orcamento=orcamento, descricao='Exame', valor=100, clinica=clinica)
        db.session.add_all([consulta, orcamento, item])
        db.session.commit()
        orcamento_id = orcamento.id

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)

        class FakePrefService:
            def create(self, data):
                return {'status': 201, 'response': {'init_point': 'http://mp-orcamento', 'id': 'pref-2'}}

        class FakeSDK:
            def preference(self):
                return FakePrefService()

        monkeypatch.setattr(app_module, 'mp_sdk', lambda: FakeSDK())
        resp = client.post(f'/orcamento/{orcamento_id}/pagar', headers={'Accept': 'application/json'})
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['success']
        assert payload['payment_link'] == 'http://mp-orcamento'
        assert payload['payment_status'] == 'pending'

    with app.app_context():
        orcamento = Orcamento.query.get(orcamento_id)
        assert orcamento.payment_link == 'http://mp-orcamento'
        assert orcamento.payment_status == 'pending'
        db.drop_all()
