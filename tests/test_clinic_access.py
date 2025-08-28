import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Clinica, Veterinario, Animal


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def login(monkeypatch, user):
    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def test_user_cannot_access_other_clinic(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        user = User(name="User", email="user@example.com", password_hash="x")
        vet = Veterinario(user=user, crmv="123", clinica=c1)
        db.session.add_all([c1, c2, user, vet])
        db.session.commit()
        login(monkeypatch, user)
        resp = client.get(f"/clinica/{c2.id}")
        assert resp.status_code == 404


def test_user_sees_own_clinic(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        user = User(name="User", email="user3@example.com", password_hash="x")
        vet = Veterinario(user=user, crmv="123", clinica=c1)
        db.session.add_all([c1, user, vet])
        db.session.commit()
        login(monkeypatch, user)
        resp = client.get(f"/clinica/{c1.id}")
        assert resp.status_code == 200
        assert b"Clinic One" in resp.data


def test_admin_can_access_any_clinic(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        admin = User(name="Admin", email="admin@example.com", password_hash="x", role="admin")
        db.session.add_all([c1, c2, admin])
        db.session.commit()
        login(monkeypatch, admin)
        resp = client.get(f"/clinica/{c2.id}")
        assert resp.status_code == 200


def test_vet_cannot_access_other_clinic_consulta(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        tutor = User(name="Tutor", email="tutor@example.com", password_hash="x")
        animal = Animal(name="Rex", owner=tutor, clinica=c2)
        user = User(name="User", email="user2@example.com", password_hash="x", worker="veterinario")
        vet = Veterinario(user=user, crmv="123", clinica=c1)
        db.session.add_all([c1, c2, tutor, animal, user, vet])
        db.session.commit()
        login(monkeypatch, user)
        resp = client.get(f"/consulta/{animal.id}")
        assert resp.status_code == 404


def test_colaborador_cannot_access_other_clinic_consulta(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        tutor = User(name="Tutor", email="tutor3@example.com", password_hash="x")
        animal = Animal(name="Rex", owner=tutor, clinica=c2)
        colaborador = User(name="Colab", email="colab@example.com", password_hash="x",
                           worker="colaborador", clinica=c1)
        db.session.add_all([c1, c2, tutor, animal, colaborador])
        db.session.commit()
        login(monkeypatch, colaborador)
        resp = client.get(f"/consulta/{animal.id}")
        assert resp.status_code == 404


def test_admin_can_access_any_consulta(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        admin = User(name="Admin", email="admin2@example.com", password_hash="x", role="admin", worker="veterinario")
        tutor = User(name="Tutor", email="tutor2@example.com", password_hash="y")
        animal = Animal(name="Rex", owner=tutor, clinica=c2)
        vet_admin = Veterinario(user=admin, crmv="999", clinica=c1)
        db.session.add_all([c1, c2, admin, tutor, animal, vet_admin])
        db.session.commit()
        login(monkeypatch, admin)
        resp = client.get(f"/consulta/{animal.id}")
        assert resp.status_code == 200
