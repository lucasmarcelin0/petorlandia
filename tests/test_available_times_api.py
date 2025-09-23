import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, time, date
from zoneinfo import ZoneInfo

import pytest

from app import app as flask_app, db
from helpers import BR_TZ, get_available_times
from models import Appointment, Clinica, Veterinario, VetSchedule, Animal, User


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


def _create_basic_entities():
    clinic = Clinica(id=1, nome="Clinica")
    tutor = User(id=1, name="Tutor", email="tutor@test")
    tutor.set_password("x")
    vet_user = User(id=2, name="Vet", email="vet@test", worker="veterinario")
    vet_user.set_password("x")
    vet = Veterinario(id=1, user_id=vet_user.id, crmv="123", clinica_id=clinic.id)
    animal = Animal(id=1, name="Rex", user_id=tutor.id, clinica_id=clinic.id)

    schedules = [
        VetSchedule(
            id=1,
            veterinario_id=vet.id,
            dia_semana="Segunda",
            hora_inicio=time(13, 0),
            hora_fim=time(17, 30),
        ),
        VetSchedule(
            id=2,
            veterinario_id=vet.id,
            dia_semana="Segunda",
            hora_inicio=time(13, 0),
            hora_fim=time(17, 30),
        ),
        VetSchedule(
            id=3,
            veterinario_id=vet.id,
            dia_semana="Segunda",
            hora_inicio=time(20, 0),
            hora_fim=time(21, 30),
        ),
    ]

    appt_local = datetime(2024, 5, 20, 13, 0, tzinfo=BR_TZ)
    appt_utc = appt_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    appointment = Appointment(
        id=1,
        veterinario_id=vet.id,
        tutor_id=tutor.id,
        animal_id=animal.id,
        clinica_id=clinic.id,
        scheduled_at=appt_utc,
        status="scheduled",
        kind="consulta",
    )

    db.session.add_all([clinic, tutor, vet_user, vet, animal, appointment, *schedules])
    db.session.commit()
    return vet


def test_available_times_endpoint_marks_booked_slots(client):
    with flask_app.app_context():
        vet = _create_basic_entities()
        target_date = date(2024, 5, 20)

        data_with_status = get_available_times(vet.id, target_date, include_booked=True)
        available_only = get_available_times(vet.id, target_date)

        assert isinstance(data_with_status, dict)
        assert sorted(data_with_status["available"]) == sorted(available_only)
        assert "13:00" not in data_with_status["available"]
        assert "13:00" in data_with_status["booked"]
        assert len(data_with_status["available"]) == len(set(data_with_status["available"]))

    resp_full = client.get(f"/api/specialist/{vet.id}/available_times?date=2024-05-20&include_booked=1")
    assert resp_full.status_code == 200
    payload = resp_full.get_json()
    assert "booked" in payload
    assert "13:00" in payload["booked"]
    assert len(payload["available"]) == len(set(payload["available"]))

    resp_simple = client.get(f"/api/specialist/{vet.id}/available_times?date=2024-05-20")
    assert resp_simple.status_code == 200
    assert resp_simple.get_json() == payload["available"]
