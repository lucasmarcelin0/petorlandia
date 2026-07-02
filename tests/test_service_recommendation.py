import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from app import app as flask_app, db
from models import User, Animal


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.drop_all()
            db.create_all()
        yield client
        with flask_app.app_context():
            db.drop_all()


def login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def _setup():
    admin = User(id=2, name='Admin', email='admin@test', role='admin')
    admin.set_password('x')
    tutor = User(id=1, name='Sebastiana Silva', email='seb@test',
                 role='adotante', phone='16999887766')
    tutor.set_password('x')
    animal = Animal(id=1, name='Bobby', user_id=tutor.id)
    db.session.add_all([admin, tutor, animal])
    db.session.commit()
    return admin, tutor, animal


def test_admin_gera_recomendacao(client, monkeypatch):
    with flask_app.app_context():
        admin, tutor, animal = _setup()
        admin_id, tutor_id = admin.id, tutor.id

    fake_admin = type('U', (), {
        'id': admin_id, 'role': 'admin', 'worker': None,
        'is_authenticated': True, 'clinica_id': None, 'name': 'Admin',
    })()
    login(monkeypatch, fake_admin)

    resp = client.post('/servicos/recomendar', json={
        'tutor_id': tutor_id,
        'services': ['vacinas', 'pmo'],
        'animal_ids': [1],
        'cidade': 'Orlândia',
        'texto_livre': 'Qualquer dúvida, me chama!',
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['phone_ok'] is True
    assert data['whatsapp_url'].startswith('https://wa.me/')
    # Mensagem personalizada, com link de primeiro acesso e nome do pet.
    assert 'Sebastiana' in data['message']
    assert 'Bobby' in data['message']
    # Link personalizado de primeiro acesso (com token assinado).
    assert '/primeiro-acesso?token=' in data['message']
    assert 'Qualquer dúvida' in data['message']


def test_sem_servico_400(client, monkeypatch):
    with flask_app.app_context():
        admin, tutor, animal = _setup()
        admin_id, tutor_id = admin.id, tutor.id
    fake_admin = type('U', (), {
        'id': admin_id, 'role': 'admin', 'worker': None,
        'is_authenticated': True, 'clinica_id': None, 'name': 'Admin',
    })()
    login(monkeypatch, fake_admin)
    resp = client.post('/servicos/recomendar', json={'tutor_id': tutor_id, 'services': []})
    assert resp.status_code == 400


def test_nao_admin_403(client, monkeypatch):
    with flask_app.app_context():
        admin, tutor, animal = _setup()
        tutor_id = tutor.id
    fake_tutor = type('U', (), {
        'id': tutor_id, 'role': 'adotante', 'worker': None,
        'is_authenticated': True, 'clinica_id': None, 'name': 'Sebastiana',
    })()
    login(monkeypatch, fake_tutor)
    resp = client.post('/servicos/recomendar', json={
        'tutor_id': tutor_id, 'services': ['pmo'],
    })
    assert resp.status_code in (403, 404)
