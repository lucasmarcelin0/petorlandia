import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Animal, Clinica

@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_imprimir_vacinas_no_login(app):
    with app.app_context():
        db.create_all()
        owner = User(name="Tutor", email="tutor@example.com", password_hash="x")
        animal = Animal(name="Rex", owner=owner)
        clinica = Clinica(nome="Pet Clinic")
        db.session.add_all([owner, animal, clinica])
        db.session.commit()
        client = app.test_client()
        resp = client.get(f"/animal/{animal.id}/vacinas/imprimir")
        assert resp.status_code == 200
        assert b"Rex" in resp.data
        assert b"Pet Clinic" in resp.data
