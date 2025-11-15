import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Clinica, ClinicStaff, Veterinario


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
        db.drop_all()
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


def test_owner_can_add_staff(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinic = Clinica(nome="Clinic")
        owner = User(name="Owner", email="o@example.com", password_hash="x")
        staff_user = User(name="Staff", email="s@example.com", password_hash="y")
        db.session.add_all([clinic, owner, staff_user])
        db.session.commit()
        clinic.owner_id = owner.id
        db.session.commit()
        login(monkeypatch, owner)
        resp = client.post(
            f"/clinica/{clinic.id}/funcionarios",
            data={"email": "s@example.com"},
            follow_redirects=True,
        )
        assert b"Permiss\xc3\xb5es do Funcion\xc3\xa1rio" in resp.data
        staff = ClinicStaff.query.filter_by(clinic_id=clinic.id, user_id=staff_user.id).first()
        assert staff is not None


def test_owner_can_add_staff_json(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinic = Clinica(nome="Clinic")
        owner = User(name="Owner", email="o@example.com", password_hash="x")
        staff_user = User(name="Staff", email="s@example.com", password_hash="y")
        db.session.add_all([clinic, owner, staff_user])
        db.session.commit()
        clinic.owner_id = owner.id
        db.session.commit()
        login(monkeypatch, owner)
        resp = client.post(
            f"/clinica/{clinic.id}/funcionarios",
            data={"email": "s@example.com"},
            headers={'Accept': 'application/json'}
        )
        assert resp.status_code == 200
        assert resp.json['success'] is True
        assert "s@example.com" in resp.json['html']


def test_add_staff_forbidden_json(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinic = Clinica(nome="Clinic")
        owner = User(name="Owner", email="o@example.com", password_hash="x")
        other = User(name="Other", email="other@example.com", password_hash="x")
        db.session.add_all([clinic, owner, other])
        db.session.commit()
        clinic.owner_id = owner.id
        db.session.commit()
        login(monkeypatch, other)
        resp = client.post(
            f"/clinica/{clinic.id}/funcionarios",
            data={"email": "o@example.com"},
            headers={'Accept': 'application/json'}
        )
        assert resp.status_code == 403
        assert resp.json['success'] is False


def test_veterinarian_added_as_staff_appears(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinic = Clinica(nome="Clinic")
        owner = User(name="Owner", email="o@example.com", password_hash="x")
        vet_user = User(name="Vet", email="v@example.com", password_hash="y", worker='veterinario')
        vet = Veterinario(user=vet_user, crmv='123')
        db.session.add_all([clinic, owner, vet_user, vet])
        db.session.commit()
        clinic.owner_id = owner.id
        db.session.add(clinic)
        db.session.commit()
        login(monkeypatch, owner)
        client.post(f"/clinica/{clinic.id}/funcionarios", data={"email": "v@example.com"})
        assert vet.clinica_id == clinic.id
        resp = client.get(f"/clinica/{clinic.id}")
        assert b"Vet" in resp.data


def test_vet_worker_without_record_shows_as_staff(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinic = Clinica(nome="Clinic")
        owner = User(name="Owner", email="o@example.com", password_hash="x")
        temp_vet = User(
            name="TempVet", email="t@example.com", password_hash="y", worker="veterinario"
        )
        db.session.add_all([clinic, owner, temp_vet])
        db.session.commit()
        clinic.owner_id = owner.id
        db.session.add(clinic)
        db.session.commit()
        login(monkeypatch, owner)
        client.post(
            f"/clinica/{clinic.id}/funcionarios",
            data={"email": "t@example.com"},
            follow_redirects=True,
        )
        resp = client.get(f"/clinica/{clinic.id}")
        assert b"TempVet" in resp.data
