import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from datetime import datetime, time, date
from zoneinfo import ZoneInfo
from app import app as flask_app, db
from models import User, Animal, Veterinario, Clinica, VetSchedule, Appointment
from helpers import BR_TZ


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


def test_weekly_schedule_api_returns_slots(client):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome="Clinica")
        tutor = User(id=1, name="Tutor", email="tutor@test")
        tutor.set_password("x")
        animal = Animal(id=1, name="Rex", user_id=tutor.id, clinica_id=clinic.id)
        vet_user = User(id=2, name="Vet", email="vet@test", worker="veterinario")
        vet_user.set_password("x")
        vet = Veterinario(id=1, user_id=vet_user.id, crmv="123", clinica_id=clinic.id)
        schedule = VetSchedule(
            id=1,
            veterinario_id=1,
            dia_semana="Segunda",
            hora_inicio=time(9, 0),
            hora_fim=time(11, 0),
        )
        appt_time_local = datetime(2024, 5, 6, 9, 30, tzinfo=BR_TZ)
        appt_time = appt_time_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        appt = Appointment(
            id=1,
            veterinario_id=1,
            tutor_id=tutor.id,
            animal_id=animal.id,
            clinica_id=clinic.id,
            scheduled_at=appt_time,
            status="scheduled",
        )
        db.session.add_all([clinic, tutor, animal, vet_user, vet, schedule, appt])
        db.session.commit()

    resp = client.get("/api/specialist/1/weekly_schedule?start=2024-05-06&days=1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data[0]["date"] == "2024-05-06"
    assert "09:00" in data[0]["available"]
    assert "09:30" in data[0]["booked"]
    assert "08:00" in data[0]["not_working"]
