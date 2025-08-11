import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, time

import pytest

from app import app as flask_app, db
from models import User, Veterinario, VetSchedule
from helpers import is_slot_available


@pytest.fixture
def app_context():
    flask_app.config.update(SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    with flask_app.app_context():
        db.create_all()
        yield
        db.drop_all()


def test_interval_blocks_slot(app_context):
    user = User(name="Vet", email="vet@test", worker="veterinario")
    user.set_password("x")
    db.session.add(user)
    db.session.commit()
    vet = Veterinario(user_id=user.id, crmv="123")
    db.session.add(vet)
    db.session.commit()
    schedule = VetSchedule(
        veterinario_id=vet.id,
        dia_semana="Quarta",
        hora_inicio=time(9, 0),
        hora_fim=time(17, 0),
        intervalo_inicio=time(12, 0),
        intervalo_fim=time(13, 0),
    )
    db.session.add(schedule)
    db.session.commit()

    assert is_slot_available(vet.id, datetime(2024, 5, 1, 11, 0)) is True
    assert is_slot_available(vet.id, datetime(2024, 5, 1, 12, 30)) is False

