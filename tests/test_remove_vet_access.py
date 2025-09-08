import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from routes.app import app as flask_app, db
from models import User, Clinica, Veterinario, ClinicStaff

@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app

def login(monkeypatch, user):
    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)

def test_removed_vet_cannot_access_clinic(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinic = Clinica(nome="Clinic")
        owner = User(name="Owner", email="o@example.com", password_hash="x")
        vet_user = User(name="Vet", email="v@example.com", password_hash="y")
        vet = Veterinario(user=vet_user, crmv="123", clinica=clinic)
        db.session.add_all([clinic, owner, vet_user, vet])
        db.session.commit()
        clinic.owner_id = owner.id
        staff = ClinicStaff(clinic_id=clinic.id, user_id=vet_user.id)
        vet_user.clinica_id = clinic.id
        db.session.add_all([staff, clinic, vet_user])
        db.session.commit()

        # Vet can access initially
        login(monkeypatch, vet_user)
        resp = client.get('/minha-clinica')
        assert resp.status_code == 302
        assert f"/clinica/{clinic.id}" in resp.headers['Location']

        # Owner removes vet
        login(monkeypatch, owner)
        client.post(f'/clinica/{clinic.id}/veterinario/{vet.id}/remove')

        # Vet no longer has access to the old clinic
        login(monkeypatch, vet_user)
        resp = client.get(f'/clinica/{clinic.id}')
        assert resp.status_code == 404

        # But can create a new clinic
        resp = client.get('/minha-clinica')
        assert resp.status_code == 200
        assert b'Criar Cl' in resp.data
