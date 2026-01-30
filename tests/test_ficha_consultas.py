import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Clinica, Veterinario, Animal, Consulta


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    with flask_app.app_context():
        db.create_all()
    yield flask_app


def login(monkeypatch, user):
    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def test_tutor_sees_consultas_from_all_clinics(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        tutor = User(name="Tutor", email="tutor@example.com", password_hash="x")
        animal = Animal(name="Rex", owner=tutor, clinica=c1)
        vet1_user = User(name="VetOne", email="v1@example.com", password_hash="x", worker="veterinario")
        vet1 = Veterinario(user=vet1_user, crmv="111", clinica=c1)
        vet2_user = User(name="VetTwo", email="v2@example.com", password_hash="x", worker="veterinario")
        vet2 = Veterinario(user=vet2_user, crmv="222", clinica=c2)
        db.session.add_all([c1, c2, tutor, animal, vet1_user, vet1, vet2_user, vet2])
        db.session.commit()
        consulta1 = Consulta(animal_id=animal.id, created_by=vet1_user.id, clinica_id=c1.id, status='finalizada')
        consulta2 = Consulta(animal_id=animal.id, created_by=vet2_user.id, clinica_id=c2.id, status='finalizada')
        db.session.add_all([consulta1, consulta2])
        db.session.commit()
        login(monkeypatch, tutor)
        resp = client.get(f"/animal/{animal.id}/ficha")
        assert resp.status_code == 200
        assert b"VetOne" in resp.data
        assert b"VetTwo" in resp.data
