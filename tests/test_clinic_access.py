import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Clinica, Veterinario


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
