import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils

from routes.app import app as flask_app, db
from models import User, Clinica, Veterinario


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    flask_app.jinja_env.globals['csrf_token'] = lambda: ''
    yield flask_app


def test_colleague_schedules_hidden(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinica = Clinica(nome="Pet Clinic")
        main_user = User(name="Main", email="m@example.com", password_hash="x", worker='veterinario')
        main_vet = Veterinario(user=main_user, crmv="1", clinica=clinica)
        col_user = User(name="Col", email="c@example.com", password_hash="x", worker='veterinario')
        col_vet = Veterinario(user=col_user, crmv="2", clinica=clinica)
        db.session.add_all([clinica, main_user, main_vet, col_user, col_vet])
        db.session.commit()
        monkeypatch.setattr(login_utils, '_get_user', lambda: main_user)
        resp = client.get('/appointments')
        assert resp.status_code == 200
        assert b'Agendas dos Colegas' not in resp.data
