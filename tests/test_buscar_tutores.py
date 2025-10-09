import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils

from app import app as flask_app, db, TUTOR_SEARCH_LIMIT
from models import User, Clinica


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
        db.drop_all()


def login(monkeypatch, user):
    user_id = getattr(user, 'id', user)

    def _load_user():
        return User.query.get(user_id)

    monkeypatch.setattr(login_utils, '_get_user', _load_user)


def test_buscar_tutores_respects_limit(app):
    with app.app_context():
        for idx in range(TUTOR_SEARCH_LIMIT + 10):
            user = User(
                name=f"Tutor {idx:03d}",
                email=f"tutor{idx}@example.com",
                password_hash="hash",
                is_private=False,
            )
            db.session.add(user)
        db.session.commit()

    client = app.test_client()
    response = client.get('/buscar_tutores?q=Tutor')

    assert response.status_code == 200

    data = response.get_json()

    assert len(data) == TUTOR_SEARCH_LIMIT
    names = [item['name'] for item in data]
    assert names == sorted(names)
    assert f"Tutor {TUTOR_SEARCH_LIMIT:03d}" not in names


def test_buscar_tutores_hides_private_profiles_for_guests(app):
    with app.app_context():
        clinic = Clinica(nome='Clínica 1')
        db.session.add(clinic)
        db.session.flush()

        public_user = User(
            name='Tutor Público',
            email='public@example.com',
            password_hash='hash',
            is_private=False,
        )
        private_user = User(
            name='Tutor Privado',
            email='private@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            is_private=True,
        )
        db.session.add_all([public_user, private_user])
        db.session.commit()

    client = app.test_client()
    response = client.get('/buscar_tutores?q=Tutor')
    assert response.status_code == 200
    names = {item['name'] for item in response.get_json()}
    assert 'Tutor Público' in names
    assert 'Tutor Privado' not in names


def test_buscar_tutores_shows_private_profiles_to_own_clinic(app, monkeypatch):
    with app.app_context():
        clinic = Clinica(nome='Clínica 1')
        db.session.add(clinic)
        db.session.flush()

        staff = User(
            name='Staff',
            email='staff@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            is_private=False,
        )
        private_user = User(
            name='Tutor Privado',
            email='private@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            is_private=True,
        )
        db.session.add_all([staff, private_user])
        db.session.commit()
        staff_id = staff.id

    login(monkeypatch, staff_id)
    client = app.test_client()
    response = client.get('/buscar_tutores?q=Tutor')
    assert response.status_code == 200
    names = {item['name'] for item in response.get_json()}
    assert 'Tutor Privado' in names
