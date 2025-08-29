import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Clinica, ClinicStaff


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def login(monkeypatch, user):
    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def test_dashboard_tabs_respect_permissions(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinic = Clinica(nome="Clinic")
        owner = User(name="Owner", email="o@example.com", password_hash="x")
        db.session.add_all([clinic, owner])
        db.session.commit()
        clinic.owner_id = owner.id
        staff_user = User(name="Staff", email="s@example.com", password_hash="y", clinica_id=clinic.id)
        db.session.add(staff_user)
        db.session.commit()
        staff = ClinicStaff(clinic_id=clinic.id, user_id=staff_user.id, can_manage_clients=True)
        db.session.add(staff)
        db.session.commit()
        login(monkeypatch, staff_user)
        resp = client.get(f"/clinica/{clinic.id}/dashboard")
        assert b"Clientes" in resp.data
        assert b"Animais" not in resp.data
