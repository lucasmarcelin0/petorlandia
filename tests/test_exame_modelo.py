import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, ExameModelo


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_criar_exame_modelo(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(name="Vet", email="vet@example.com", worker="veterinario", role="admin")
        user.set_password("x")
        db.session.add(user)
        db.session.commit()

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.post('/exame_modelo', json={'nome': 'Hemograma'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['nome'] == 'Hemograma'
        with app.app_context():
            exame = ExameModelo.query.first()
            assert exame and exame.nome == 'Hemograma'


def test_criar_exame_modelo_nome_obrigatorio(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(name="Vet", email="vet@example.com")
        user.set_password("x")
        db.session.add(user)
        db.session.commit()

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.post('/exame_modelo', json={})
        assert resp.status_code == 400
