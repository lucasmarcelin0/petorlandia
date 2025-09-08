import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from app import app as flask_app, db
from models import User, Animal


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    yield flask_app


def test_user_cannot_delete_other_users_animal(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        u1 = User(id=1, name='User1', email='u1@test')
        u1.set_password('x')
        u2 = User(id=2, name='User2', email='u2@test')
        u2.set_password('x')
        animal = Animal(id=1, name='Dog', user_id=u1.id, added_by_id=u1.id)
        db.session.add_all([u1, u2, animal])
        db.session.commit()
        fake_user = type('U', (), {
            'id': u2.id,
            'role': 'adotante',
            'worker': None,
            'is_authenticated': True,
        })()
        monkeypatch.setattr(login_utils, '_get_user', lambda: fake_user)
    resp = client.post('/animal/1/deletar', headers={'Accept': 'application/json'})
    assert resp.status_code == 403
    with app.app_context():
        assert Animal.query.get(1).removido_em is None


def test_user_can_delete_own_animal(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        u1 = User(id=1, name='User1', email='u1@test')
        u1.set_password('x')
        animal = Animal(id=1, name='Dog', user_id=u1.id, added_by_id=u1.id)
        db.session.add_all([u1, animal])
        db.session.commit()
        fake_user = type('U', (), {
            'id': u1.id,
            'role': 'adotante',
            'worker': None,
            'is_authenticated': True,
        })()
        monkeypatch.setattr(login_utils, '_get_user', lambda: fake_user)
    resp = client.post('/animal/1/deletar', headers={'Accept': 'application/json'})
    assert resp.status_code == 200
    assert resp.json['deleted'] is True
    with app.app_context():
        assert Animal.query.get(1).removido_em is not None


def test_user_who_added_animal_can_delete(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        tutor = User(id=1, name='Tutor', email='t@test')
        tutor.set_password('x')
        vet = User(id=2, name='Vet', email='v@test')
        vet.set_password('x')
        animal = Animal(id=1, name='Dog', user_id=tutor.id, added_by_id=vet.id)
        db.session.add_all([tutor, vet, animal])
        db.session.commit()
        fake_vet = type('U', (), {
            'id': vet.id,
            'role': 'adotante',
            'worker': None,
            'is_authenticated': True,
        })()
        monkeypatch.setattr(login_utils, '_get_user', lambda: fake_vet)
    resp = client.post('/animal/1/deletar', headers={'Accept': 'application/json'})
    assert resp.status_code == 200
    assert resp.json['deleted'] is True


def test_vet_cannot_delete_tutor_added_by_other_vet(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        vet1 = User(id=1, name='Vet1', email='v1@test', worker='veterinario')
        vet1.set_password('x')
        vet2 = User(id=2, name='Vet2', email='v2@test', worker='veterinario')
        vet2.set_password('x')
        tutor = User(id=3, name='Tutor', email='t@test', added_by_id=vet1.id)
        tutor.set_password('x')
        db.session.add_all([vet1, vet2, tutor])
        db.session.commit()
        tutor_id = tutor.id
        fake_vet = type('U', (), {
            'id': vet2.id,
            'role': 'adotante',
            'worker': 'veterinario',
            'is_authenticated': True,
        })()
        monkeypatch.setattr(login_utils, '_get_user', lambda: fake_vet)
    resp = client.post(f'/deletar_tutor/{tutor_id}', headers={'Accept': 'application/json'})
    assert resp.status_code == 403
    with app.app_context():
        assert User.query.get(tutor_id) is not None


def test_vet_can_delete_tutor_he_added(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        vet = User(id=1, name='Vet', email='v@test', worker='veterinario')
        vet.set_password('x')
        tutor = User(id=2, name='Tutor', email='t@test', added_by_id=vet.id)
        tutor.set_password('x')
        db.session.add_all([vet, tutor])
        db.session.commit()
        tutor_id = tutor.id
        fake_vet = type('U', (), {
            'id': vet.id,
            'role': 'adotante',
            'worker': 'veterinario',
            'is_authenticated': True,
        })()
        monkeypatch.setattr(login_utils, '_get_user', lambda: fake_vet)
    resp = client.post(f'/deletar_tutor/{tutor_id}')
    assert resp.status_code == 302
    with app.app_context():
        assert User.query.get(tutor_id) is None
