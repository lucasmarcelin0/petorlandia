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


def test_minha_clinica_page(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinica = Clinica(nome="Pet Clinic")
        user = User(name="Vet", email="vet@example.com", password_hash="x", worker="veterinario")
        vet = Veterinario(user=user, crmv="123", clinica=clinica)
        db.session.add_all([clinica, user, vet])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)

        resp = client.get('/minha-clinica')
        assert resp.status_code == 200
        assert f"/clinica/{clinica.id}" in resp.get_data(as_text=True)
