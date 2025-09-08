import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from routes.app import app as flask_app, db
from models import User, ExameModelo


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app
    with flask_app.app_context():
        db.drop_all()


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
        resp = client.post('/exame_modelo', json={'nome': 'Hemograma', 'justificativa': 'Exame de rotina'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['nome'] == 'Hemograma'
        assert data['justificativa'] == 'Exame de rotina'
        with app.app_context():
            exame = ExameModelo.query.first()
            user_db = User.query.filter_by(email='vet@example.com').first()
            assert exame and exame.nome == 'Hemograma'
            assert exame.justificativa == 'Exame de rotina'
            assert user_db and exame.created_by == user_db.id


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


def test_exame_modelo_delete_restrito(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        user1 = User(name="Vet", email="vet@example.com")
        user1.set_password("x")
        user2 = User(name="Outro", email="outro@example.com")
        user2.set_password("x")
        db.session.add_all([user1, user2])
        db.session.commit()

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.post('/exame_modelo', json={'nome': 'Raio X'})
        exame_id = resp.get_json()['id']
        client.get('/logout')
        client.post('/login', data={'email': 'outro@example.com', 'password': 'x'}, follow_redirects=True)
        resp_del = client.delete(f'/exame_modelo/{exame_id}')
        assert resp_del.status_code == 403
