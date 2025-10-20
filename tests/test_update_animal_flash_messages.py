import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

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


def test_update_animal_json_does_not_flash(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        vet = User(id=1, name='Vet', email='vet@example.com', worker='veterinario')
        vet.set_password('secret')
        animal = Animal(id=1, name='Doggo', user_id=vet.id)

        db.session.add_all([vet, animal])
        db.session.commit()

        import flask_login.utils as login_utils

        fake_user = type(
            'FakeVet',
            (),
            {
                'id': vet.id,
                'worker': 'veterinario',
                'is_authenticated': True,
            },
        )()

        monkeypatch.setattr(login_utils, '_get_user', lambda: fake_user)

    response = client.post(
        '/update_animal/1',
        data={'name': 'Doggo', 'species_id': 'abc'},
        headers={'Accept': 'application/json'},
    )

    assert response.status_code == 200
    assert response.json['success'] is True

    with client.session_transaction() as session_data:
        assert '_flashes' not in session_data
