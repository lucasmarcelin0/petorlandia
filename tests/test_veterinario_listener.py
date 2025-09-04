import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Veterinario


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_veterinario_created_on_insert(app):
    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(name="Vet", email="v@example.com", password_hash="x", worker="veterinario")
        db.session.add(user)
        db.session.commit()

        vet = Veterinario.query.filter_by(user_id=user.id).first()
        assert vet is not None
        assert vet.crmv == ""


def test_veterinario_create_and_remove_on_update(app):
    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(name="User", email="u@example.com", password_hash="x", worker=None)
        db.session.add(user)
        db.session.commit()
        assert Veterinario.query.count() == 0

        user.worker = "veterinario"
        db.session.commit()
        assert Veterinario.query.filter_by(user_id=user.id).first() is not None

        user.worker = "doador"
        db.session.commit()
        assert Veterinario.query.filter_by(user_id=user.id).first() is None
