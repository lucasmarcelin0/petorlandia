import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Animal, Clinica, Vacina, VacinaModelo

@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app
    with flask_app.app_context():
        db.drop_all()


def test_imprimir_vacinas_requer_clinica(app):
    with app.app_context():
        db.create_all()
        owner = User(name="Tutor", email="tutor@example.com", password_hash="x")
        animal = Animal(name="Rex", owner=owner)
        clinica = Clinica(nome="Pet Clinic")
        db.session.add_all([owner, animal, clinica])
        db.session.commit()
        client = app.test_client()
        resp = client.get(f"/animal/{animal.id}/vacinas/imprimir")
        assert resp.status_code == 400
        resp = client.get(f"/animal/{animal.id}/vacinas/imprimir?clinica_id={clinica.id}")
        assert resp.status_code == 200
        assert b"Rex" in resp.data
        assert b"Pet Clinic" in resp.data


def test_salvar_vacina_data_invalida(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        owner = User(name="Tutor", email="tutor@example.com", password_hash="x")
        animal = Animal(name="Rex", owner=owner)
        db.session.add_all([owner, animal])
        db.session.commit()

        client = app.test_client()
        payload = {"vacinas": [{"nome": "Antirrabica", "tipo": "Teste", "data": "111111-11-11"}]}
        resp = client.post(f"/animal/{animal.id}/vacinas", json=payload)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

        vacina = Vacina.query.filter_by(animal_id=animal.id).first()
        assert vacina is not None
        assert vacina.data is None


def test_criar_vacina_modelo(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(name="Vet", email="vet@example.com")
        user.set_password("x")
        db.session.add(user)
        db.session.commit()
        client = app.test_client()
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.post('/vacina_modelo', json={
            'nome': 'V10',
            'tipo': 'Obrigatória',
            'fabricante': 'ACME',
            'doses_totais': 3,
            'intervalo_dias': 30,
            'frequencia': 'Anual'
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        vm = VacinaModelo.query.filter_by(nome='V10').first()
        assert vm is not None and vm.created_by == user.id
        assert vm.fabricante == 'ACME'
        assert vm.doses_totais == 3
        assert vm.intervalo_dias == 30
        assert vm.frequencia == 'Anual'


def test_buscar_vacinas_campos(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(name="Vet", email="vet@example.com", password_hash="x")
        db.session.add(user)
        db.session.commit()

        vm = VacinaModelo(
            nome="V8",
            tipo="Obrigatória",
            fabricante="ACME",
            doses_totais=3,
            intervalo_dias=30,
            frequencia="Anual",
            created_by=user.id,
        )
        db.session.add(vm)
        db.session.commit()

        client = app.test_client()
        resp = client.get('/buscar_vacinas?q=V8')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list) and len(data) == 1
        item = data[0]
        assert item['id'] == vm.id
        assert item['fabricante'] == 'ACME'
        assert item['doses_totais'] == 3
        assert item['intervalo_dias'] == 30
        assert item['frequencia'] == 'Anual'


def test_fluxo_criacao_edicao_vacina(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        tutor = User(name="Tutor", email="tutor@example.com", password_hash="x")
        animal = Animal(name="Rex", owner=tutor)
        vet = User(name="Vet", email="vet@example.com", worker="veterinario")
        vet.set_password("x")
        db.session.add_all([tutor, animal, vet])
        db.session.commit()

        client = app.test_client()
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)

        payload = {
            'vacinas': [
                {
                    'nome': 'V10',
                    'tipo': 'Obrigatória',
                    'data': '2024-01-01',
                    'fabricante': 'ACME',
                    'doses_totais': 3,
                    'intervalo_dias': 30,
                    'frequencia': 'Anual'
                }
            ]
        }
        resp = client.post(f'/animal/{animal.id}/vacinas', json=payload)
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        vac = Vacina.query.filter_by(animal_id=animal.id, nome='V10').first()
        assert vac is not None and vac.fabricante == 'ACME'

        resp = client.put(f'/vacina/{vac.id}', json={
            'nome': 'V10X',
            'tipo': 'Reforço',
            'fabricante': 'XYZ',
            'doses_totais': 2,
            'intervalo_dias': 60,
            'frequencia': 'Bienal',
            'data': '2024-02-01'
        })
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        vac2 = Vacina.query.get(vac.id)
        assert vac2.nome == 'V10X'
        assert vac2.intervalo_dias == 60
