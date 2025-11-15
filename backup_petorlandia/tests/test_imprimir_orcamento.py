import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

import pytest
from app import app as flask_app, db
from models import User, Animal, Consulta, OrcamentoItem, Clinica, Orcamento


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_imprimir_orcamento(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        vet = User(name='Vet', email='vet@example.com', worker='veterinario', role='admin')
        vet.set_password('x')
        tutor = User(name='Tutor', email='tutor@example.com')
        tutor.set_password('y')
        animal = Animal(name='Rex', owner=tutor)
        db.session.add_all([vet, tutor, animal])
        db.session.commit()

        consulta = Consulta(animal_id=animal.id, created_by=vet.id, status='in_progress')
        db.session.add(consulta)
        db.session.commit()

        item = OrcamentoItem(consulta=consulta, descricao='Consulta', valor=50)
        db.session.add(item)
        db.session.commit()
        consulta_id = consulta.id

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.get(f'/imprimir_orcamento/{consulta_id}')
        assert resp.status_code == 200
        assert b'Consulta' in resp.data
        assert b'50.00' in resp.data

    with app.app_context():
        db.drop_all()


def test_imprimir_orcamento_preserva_veterinario_original(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        vet1 = User(name='Vet1', email='vet1@example.com', worker='veterinario', role='admin')
        vet1.set_password('x')
        vet2 = User(name='Vet2', email='vet2@example.com', worker='veterinario', role='admin')
        vet2.set_password('y')
        tutor = User(name='Tutor', email='tutor@example.com')
        tutor.set_password('z')
        animal = Animal(name='Rex', owner=tutor)
        db.session.add_all([vet1, vet2, tutor, animal])
        db.session.commit()

        consulta = Consulta(animal_id=animal.id, created_by=vet1.id, status='in_progress')
        db.session.add(consulta)
        db.session.commit()

        item = OrcamentoItem(consulta=consulta, descricao='Consulta', valor=50)
        db.session.add(item)
        db.session.commit()
        consulta_id = consulta.id

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet2@example.com', 'password': 'y'}, follow_redirects=True)
        resp = client.get(f'/imprimir_orcamento/{consulta_id}')
        assert resp.status_code == 200
        assert b'Vet1' in resp.data
        assert b'Vet2' not in resp.data

    with app.app_context():
        db.drop_all()


def test_imprimir_orcamento_padrao(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        vet = User(name='Vet', email='vet@example.com', worker='veterinario', role='admin')
        vet.set_password('x')
        clinica = Clinica(nome='Clinica X', owner=vet)
        db.session.add_all([vet, clinica])
        db.session.commit()

        o = Orcamento(clinica=clinica, descricao='Padrao')
        db.session.add(o)
        db.session.commit()

        item = OrcamentoItem(orcamento=o, descricao='Servico', valor=100)
        db.session.add(item)
        db.session.commit()
        orcamento_id = o.id

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.get(f'/orcamento/{orcamento_id}/imprimir')
        assert resp.status_code == 200
        assert b'Servico' in resp.data
        assert b'100.00' in resp.data

    with app.app_context():
        db.drop_all()

