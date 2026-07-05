import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db, list_rations
from models import User, Animal, TipoRacao, VacinaModelo, Medicamento, Veterinario


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


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _activate_veterinarian(user, crmv):
    vet_profile = Veterinario(user=user, crmv=crmv)
    db.session.add(vet_profile)
    return vet_profile


def test_list_rations_cache_survives_session_teardown(app):
    with app.app_context():
        db.create_all()
        list_rations.cache_clear()

        vet = User(name="Vet", email="vet-cache@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add(vet)
        db.session.flush()
        tipo = TipoRacao(marca="Golden", linha="Senior", recomendacao=12.5, created_by=vet.id)
        db.session.add(tipo)
        db.session.commit()
        tipo_id = tipo.id

        cached = list_rations()
        db.session.commit()
        db.session.remove()

        assert cached[0].id == tipo_id
        assert cached[0].marca == "Golden"
        assert cached[0].linha == "Senior"
        assert cached[0].recomendacao == 12.5


def test_salvar_racao_cria_tipo_com_usuario(app):
    with app.app_context():
        db.create_all()
        tutor = User(name="Tutor", email="tutor@example.com")
        tutor.set_password("x")
        vet = User(name="Vet", email="vet@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add_all([tutor, vet])
        db.session.flush()
        _activate_veterinarian(vet, "CRMVRACAO1")
        db.session.commit()
        animal = Animal(name="Rex", owner=tutor, added_by_id=vet.id)
        db.session.add(animal)
        db.session.commit()
        client = app.test_client()
        _login(client, vet)
        payload = {'racoes': [{'marca_racao': 'Purina'}]}
        resp = client.post(f'/animal/{animal.id}/racoes', json=payload)
        assert resp.status_code == 200
        tipo = TipoRacao.query.filter_by(marca='Purina').first()
        assert tipo is not None and tipo.created_by == vet.id


def test_salvar_racao_normaliza_marca_special_dog(app):
    with app.app_context():
        db.create_all()
        tutor = User(name="Tutor", email="tutor-special@example.com")
        tutor.set_password("x")
        vet = User(name="Vet", email="vet-special@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add_all([tutor, vet])
        db.session.flush()
        _activate_veterinarian(vet, "CRMVRACAO2")
        db.session.commit()
        animal = Animal(name="Rex", owner=tutor, added_by_id=vet.id)
        db.session.add(animal)
        db.session.commit()
        client = app.test_client()
        _login(client, vet)
        payload = {'racoes': [{'marca_racao': 'Especial dog'}]}
        resp = client.post(f'/animal/{animal.id}/racoes', json=payload)
        assert resp.status_code == 200
        assert TipoRacao.query.filter_by(marca='Special Dog').first() is not None
        assert TipoRacao.query.filter_by(marca='Especial dog').first() is None


def test_criar_tipo_racao_normaliza_marca_special_cat(app):
    with app.app_context():
        db.create_all()
        vet = User(name="Vet", email="vet-cat@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add(vet)
        db.session.flush()
        _activate_veterinarian(vet, "CRMVRACAO3")
        db.session.commit()
        client = app.test_client()
        _login(client, vet)
        resp = client.post('/tipo_racao', json={'marca': 'Especial cat'})
        assert resp.status_code == 200
        tipo = TipoRacao.query.get(resp.get_json()['id'])
        assert tipo.marca == 'Special Cat'


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
        _login(client, vet)
        resp = client.put(f'/tipo_racao/{tipo.id}', json={'marca': 'Nova'})
        assert resp.status_code == 200
        assert TipoRacao.query.get(tipo.id).marca == 'Nova'


def test_alterar_tipo_racao_normaliza_marca_special_dog(app):
    with app.app_context():
        db.create_all()
        vet = User(name="Vet", email="vet-update@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add(vet)
        db.session.commit()
        tipo = TipoRacao(marca='Marca', created_by=vet.id)
        db.session.add(tipo)
        db.session.commit()
        client = app.test_client()
        _login(client, vet)
        resp = client.put(f'/tipo_racao/{tipo.id}', json={'marca': 'Especial Dog'})
        assert resp.status_code == 200
        assert TipoRacao.query.get(tipo.id).marca == 'Special Dog'


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
        _login(client, vet)
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
        _login(client, vet)
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
        _login(client, vet)
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
