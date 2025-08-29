import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db
from models import User, Clinica, Veterinario, Animal

@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def login(monkeypatch, user):
    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def test_users_share_clinic_data(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinic = Clinica(nome="Clinic")
        vet_user = User(name="Vet", email="vet@example.com", password_hash="x", worker="veterinario")
        vet = Veterinario(user=vet_user, crmv="123", clinica=clinic)
        colab_user = User(name="Colab", email="colab@example.com", password_hash="y", worker="colaborador", clinica_id=clinic.id)
        db.session.add_all([clinic, vet_user, vet, colab_user])
        db.session.commit()

        # veterinarian adds tutor and animal
        login(monkeypatch, vet_user)
        client.post('/tutores', data={'name': 'Tutor', 'email': 't@t.com'})
        tutor = User.query.filter_by(email='t@t.com').first()
        assert tutor.clinica_id == clinic.id

        client.post('/novo_animal', data={'tutor_id': tutor.id, 'name': 'Rex', 'sex': 'M'})
        animal = Animal.query.filter_by(name='Rex').first()
        assert animal.clinica_id == clinic.id

        # collaborator can see tutor and animal exists in clinic
        login(monkeypatch, colab_user)
        resp = client.get('/tutores?scope=mine')
        assert b'Tutor' in resp.data
        assert Animal.query.filter_by(name='Rex', clinica_id=clinic.id).first() is not None

        db.session.remove()
        db.drop_all()
