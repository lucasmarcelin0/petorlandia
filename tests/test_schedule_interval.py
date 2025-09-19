import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, time, timedelta, timezone

import pytest

from app import app as flask_app, db
from models import User, Veterinario, VetSchedule, Animal, ExamAppointment
from helpers import is_slot_available, has_schedule_conflict, BR_TZ


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


def test_slot_unavailable_when_exam_conflicts(app_context):
    vet_user = User(name="Vet", email="vet_exam@test", worker="veterinario")
    vet_user.set_password("x")
    tutor = User(name="Tutor", email="tutor_exam@test")
    tutor.set_password("x")
    db.session.add_all([vet_user, tutor])
    db.session.commit()

    vet = Veterinario(user_id=vet_user.id, crmv="789")
    db.session.add(vet)
    db.session.commit()

    schedule = VetSchedule(
        veterinario_id=vet.id,
        dia_semana="Quarta",
        hora_inicio=time(9, 0),
        hora_fim=time(17, 0),
    )
    db.session.add(schedule)
    db.session.commit()

    animal = Animal(name="Rex", owner=tutor)
    db.session.add(animal)
    db.session.commit()

    scheduled_at_local = datetime(2024, 5, 1, 11, 0)
    scheduled_at_utc = (
        scheduled_at_local.replace(tzinfo=BR_TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    exam = ExamAppointment(
        animal_id=animal.id,
        specialist_id=vet.id,
        requester_id=tutor.id,
        scheduled_at=scheduled_at_utc,
        status='confirmed',
    )
    db.session.add(exam)
    db.session.commit()

    assert is_slot_available(vet.id, scheduled_at_local) is False
    assert is_slot_available(vet.id, scheduled_at_local + timedelta(minutes=30)) is True


def test_has_schedule_conflict(app_context):
    user = User(name="Vet", email="vet2@test", worker="veterinario")
    user.set_password("x")
    db.session.add(user)
    db.session.commit()
    vet = Veterinario(user_id=user.id, crmv="456")
    db.session.add(vet)
    db.session.commit()
    schedule = VetSchedule(
        veterinario_id=vet.id,
        dia_semana="Quarta",
        hora_inicio=time(9, 0),
        hora_fim=time(12, 0),
    )
    db.session.add(schedule)
    db.session.commit()

    assert has_schedule_conflict(vet.id, "Quarta", time(11, 0), time(13, 0)) is True
    assert has_schedule_conflict(vet.id, "Quarta", time(12, 0), time(13, 0)) is False

