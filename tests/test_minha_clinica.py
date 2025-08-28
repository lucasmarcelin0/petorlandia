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


def test_minha_clinica_redirects(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinica = Clinica(nome="Pet Clinic")
        user = User(name="Vet", email="vet@example.com", password_hash="x")
        vet = Veterinario(user=user, crmv="123", clinica=clinica)
        db.session.add_all([clinica, user, vet])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)

        resp = client.get('/minha-clinica')
        assert resp.status_code == 302
        assert f"/clinica/{clinica.id}" in resp.headers['Location']


def test_layout_shows_minha_clinica_for_veterinario(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinica = Clinica(nome="Pet Clinic")
        user = User(name="Vet", email="vet2@example.com", password_hash="x")
        vet = Veterinario(user=user, crmv="123", clinica=clinica)
        db.session.add_all([clinica, user, vet])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)

        resp = client.get('/')
        assert b'Minha Cl\xc3\xadnica' in resp.data


def test_minha_clinica_admin_defaults_to_own_clinic(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        other = Clinica(nome="Outra")
        admin = User(name="Admin", email="admin@example.com", password_hash="x", role="admin")
        db.session.add_all([admin, other])
        db.session.commit()

        mine = Clinica(nome="Minha", owner=admin)
        db.session.add(mine)
        db.session.commit()

        admin.clinica_id = mine.id
        db.session.add(admin)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)

        resp = client.get('/minha-clinica')
        assert resp.status_code == 302
        assert f"/clinica/{mine.id}" in resp.headers['Location']
