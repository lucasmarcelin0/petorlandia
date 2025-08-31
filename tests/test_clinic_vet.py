import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Clinica, Veterinario


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    yield flask_app


def test_add_veterinarian_sets_clinic(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinic = Clinica(id=1, nome='Clinica', owner_id=1)
        user = User(id=2, name='Vet', email='vet@test', password_hash='x')
        vet = Veterinario(id=1, user_id=user.id, crmv='123')
        db.session.add_all([clinic, user, vet])
        db.session.commit()

        # Simulate staff addition logic
        user.clinica_id = clinic.id
        if getattr(user, 'veterinario', None):
            user.veterinario.clinica_id = clinic.id
            db.session.add(user.veterinario)
        db.session.add(user)
        db.session.commit()

        assert vet.clinica_id == clinic.id

        db.session.remove()
        db.drop_all()
