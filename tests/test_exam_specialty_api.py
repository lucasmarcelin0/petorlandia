import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from routes.app import app as flask_app, db
from models import Specialty


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.create_all()
            db.session.add(Specialty(nome='Raio-X'))
            db.session.commit()
        yield client
        with flask_app.app_context():
            db.drop_all()


def test_specialties_access_without_login(client):
    resp = client.get('/api/specialties')
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]['nome'] == 'Raio-X'
