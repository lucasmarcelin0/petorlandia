import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

from app import app as flask_app, db, TUTOR_SEARCH_LIMIT
from models import User


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


def test_buscar_tutores_respects_limit(app):
    with app.app_context():
        for idx in range(TUTOR_SEARCH_LIMIT + 10):
            user = User(
                name=f"Tutor {idx:03d}",
                email=f"tutor{idx}@example.com",
                password_hash="hash",
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
