import os
import sys
from datetime import time

import pytest

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db
from models import User, Veterinario, VetSchedule


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
        yield client
        with flask_app.app_context():
            db.drop_all()


def test_veterinarios_listing_and_detail(client):
    with flask_app.app_context():
        user = User(id=1, name="Vet", email="vet@test", password_hash="x", worker="veterinario")
        vet = Veterinario(id=1, user=user, crmv="123")
        schedule = VetSchedule(veterinario=vet, dia_semana="Segunda", hora_inicio=time(9, 0), hora_fim=time(17, 0))
        db.session.add_all([user, vet, schedule])
        db.session.commit()

    resp = client.get("/veterinarios")
    assert resp.status_code == 200
    assert b"Vet" in resp.data

    resp = client.get("/veterinario/1")
    assert resp.status_code == 200
    assert b"CRMV" in resp.data
    assert b"123" in resp.data
    assert b"Segunda" in resp.data
