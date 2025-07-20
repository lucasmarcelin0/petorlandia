import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app
from models import User

@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield flask_app

def test_login_page(app):
    client = app.test_client()
    response = client.get('/login')
    assert response.status_code == 200

def test_login_invalid_credentials(monkeypatch, app):
    client = app.test_client()

    class FakeQuery:
        def filter_by(self, **kw):
            return self
        def first(self):
            return None

    with app.app_context():
        monkeypatch.setattr(User, 'query', FakeQuery())

    response = client.post('/login', data={'email': 'foo@bar.com', 'password': 'x'}, follow_redirects=True)
    assert b'Email ou senha inv\xc3\xa1lidos' in response.data

def test_add_animal_requires_login(app):
    client = app.test_client()
    response = client.get('/add-animal')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']

def test_loja_requires_login(app):
    client = app.test_client()
    response = client.get('/loja')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_mp_token_in_config(app):
    assert 'MERCADOPAGO_ACCESS_TOKEN' in app.config


def test_mp_webhook_secret_in_config(app):
    assert 'MERCADOPAGO_WEBHOOK_SECRET' in app.config
from models import Animal


def test_index_page(app):
    client = app.test_client()
    response = client.get('/')
    assert response.status_code == 200


def test_register_page(app):
    client = app.test_client()
    response = client.get('/register')
    assert response.status_code == 200


def test_reset_password_request_page(app):
    client = app.test_client()
    response = client.get('/reset_password_request')
    assert response.status_code == 200


def test_logout_requires_login(app):
    client = app.test_client()
    response = client.get('/logout')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_profile_requires_login(app):
    client = app.test_client()
    response = client.get('/profile')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_animals_page(monkeypatch, app):
    client = app.test_client()

    class FakePagination:
        def __init__(self):
            self.items = []
            self.pages = 0

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self
        def filter_by(self, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def paginate(self, page=None, per_page=None, error_out=True):
            return FakePagination()

    with app.app_context():
        monkeypatch.setattr(Animal, 'query', FakeQuery())

    response = client.get('/animals')
    assert response.status_code == 200
