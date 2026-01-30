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
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()


def test_added_by_user_can_view_animal(monkeypatch, app):
    """A user who registered an animal (added_by_id) can view it."""
    client = app.test_client()
    with app.app_context():
        tutor = User(id=1, name='Tutor', email='t@test')
        tutor.set_password('x')
        vet = User(id=2, name='Vet', email='v@test', worker='veterinario')
        vet.set_password('x')
        animal = Animal(id=1, name='Rex', user_id=tutor.id, added_by_id=vet.id)
        db.session.add_all([tutor, vet, animal])
        db.session.commit()
        fake_vet = type('U', (), {
            'id': vet.id,
            'role': 'adotante',
            'worker': 'veterinario',
            'is_authenticated': True,
        })()
        monkeypatch.setattr(login_utils, '_get_user', lambda: fake_vet)
    resp = client.get('/animal/1/ficha')
    assert resp.status_code != 404


def test_unrelated_user_cannot_view_clinic_animal(monkeypatch, app):
    """A user with no relation to a clinic animal gets 404."""
    from models import Clinica
    client = app.test_client()
    with app.app_context():
        clinic = Clinica(id=1, nome='Clinic')
        tutor = User(id=1, name='Tutor', email='t@test')
        tutor.set_password('x')
        stranger = User(id=2, name='Stranger', email='s@test')
        stranger.set_password('x')
        animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
        db.session.add_all([clinic, tutor, stranger, animal])
        db.session.commit()
        fake_stranger = type('U', (), {
            'id': stranger.id,
            'role': 'adotante',
            'worker': None,
            'is_authenticated': True,
            'clinica_id': None,
        })()
        monkeypatch.setattr(login_utils, '_get_user', lambda: fake_stranger)
    resp = client.get('/animal/1/ficha')
    assert resp.status_code in (403, 404)
