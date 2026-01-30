import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Animal, TipoRacao, VacinaModelo, Medicamento


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.create_all()
    yield flask_app


def _login(client, email, password):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)


def test_salvar_racao_cria_tipo_com_usuario(app):
    with app.app_context():
        db.create_all()
        tutor = User(name="Tutor", email="tutor@example.com")
        tutor.set_password("x")
        vet = User(name="Vet", email="vet@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add_all([tutor, vet])
        db.session.commit()
        animal = Animal(name="Rex", owner=tutor)
        db.session.add(animal)
        db.session.commit()
        client = app.test_client()
        _login(client, 'vet@example.com', 'x')
        payload = {'racoes': [{'marca_racao': 'Purina'}]}
        resp = client.post(f'/animal/{animal.id}/racoes', json=payload)
        assert resp.status_code == 200
        tipo = TipoRacao.query.filter_by(marca='Purina').first()
        assert tipo is not None and tipo.created_by == vet.id


def test_alterar_tipo_racao_sem_linha(app):
    with app.app_context():
        db.create_all()
        vet = User(name="Vet", email="vet@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add(vet)
        db.session.commit()
        tipo = TipoRacao(marca='Marca', created_by=vet.id)
        db.session.add(tipo)
        db.session.commit()
        client = app.test_client()
        _login(client, 'vet@example.com', 'x')
        resp = client.put(f'/tipo_racao/{tipo.id}', json={'marca': 'Nova'})
        assert resp.status_code == 200
        assert TipoRacao.query.get(tipo.id).marca == 'Nova'


def test_alterar_vacina_tipo_nulo(app):
    with app.app_context():
        db.create_all()
        vet = User(name="Vet", email="vet@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add(vet)
        db.session.commit()
        vacina = VacinaModelo(nome='V1', created_by=vet.id)
        db.session.add(vacina)
        db.session.commit()
        client = app.test_client()
        _login(client, 'vet@example.com', 'x')
        resp = client.put(f'/vacina_modelo/{vacina.id}', json={'nome': 'V1x'})
        assert resp.status_code == 200
        assert VacinaModelo.query.get(vacina.id).nome == 'V1x'


def test_alterar_medicamento_principio_nulo(app):
    with app.app_context():
        db.create_all()
        vet = User(name="Vet", email="vet@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add(vet)
        db.session.commit()
        med = Medicamento(nome='Med', created_by=vet.id)
        db.session.add(med)
        db.session.commit()
        client = app.test_client()
        _login(client, 'vet@example.com', 'x')
        resp = client.put(f'/medicamento/{med.id}', json={'nome': 'MedX'})
        assert resp.status_code == 200
        assert Medicamento.query.get(med.id).nome == 'MedX'


def test_criar_medicamento_campos_opcionais(app):
    with app.app_context():
        db.create_all()
        vet = User(name="Vet", email="vet@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add(vet)
        db.session.commit()
        client = app.test_client()
        _login(client, 'vet@example.com', 'x')
        payload = {
            'nome': 'Dipirona',
            'classificacao': 'analgésico'
        }
        resp = client.post('/medicamento', json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        med = Medicamento.query.get(data['id'])
        assert med.nome == 'Dipirona'
        assert med.classificacao == 'analgésico'
        assert med.principio_ativo is None
