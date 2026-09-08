import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, time, date, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import app as flask_app, db
from helpers import BR_TZ, is_slot_available, get_appointment_duration
from models import Appointment, ExamAppointment, Clinica, Veterinario, VetSchedule, Animal, User

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

def _create_basic_vet():
    clinic = Clinica(id=1, nome="Clinica")
    vet_user = User(id=2, name="Vet", email="vet@test", worker="veterinario")
    vet_user.set_password("x")
    vet = Veterinario(id=1, user_id=vet_user.id, crmv="123", clinica_id=clinic.id)
    db.session.add_all([clinic, vet_user, vet])
    db.session.commit()
    return vet

def _create_tutor_and_animal(clinic):
    tutor = User(name="Tutor", email=f"tutor{datetime.now().timestamp()}@test")
    tutor.set_password("x")
    db.session.add(tutor)
    db.session.flush()
    animal = Animal(name="Rex", user_id=tutor.id, clinica_id=clinic.id)
    db.session.add(animal)
    db.session.commit()
    return tutor, animal


def test_slot_available_within_hours(client):
    with flask_app.app_context():
        vet = _create_basic_vet()
        schedule = VetSchedule(
            veterinario_id=vet.id,
            dia_semana="Segunda",
            hora_inicio=time(9, 0),
            hora_fim=time(17, 0),
        )
        db.session.add(schedule)
        db.session.commit()

        # Test 10:00 AM slot on a Monday (2024-05-20 is Monday)
        slot = datetime(2024, 5, 20, 10, 0)
        assert is_slot_available(vet.id, slot) is True

        # Test boundary conditions
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 9, 0)) is True
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 16, 30)) is True


def test_slot_unavailable_outside_hours(client):
    with flask_app.app_context():
        vet = _create_basic_vet()
        schedule = VetSchedule(
            veterinario_id=vet.id,
            dia_semana="Segunda",
            hora_inicio=time(9, 0),
            hora_fim=time(17, 0),
        )
        db.session.add(schedule)
        db.session.commit()

        # Before hours
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 8, 30)) is False

        # After hours (slot is 30 mins, so 16:45 ends at 17:15)
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 16, 45)) is False
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 17, 0)) is False

        # Wrong day (Tuesday)
        assert is_slot_available(vet.id, datetime(2024, 5, 21, 10, 0)) is False


def test_slot_unavailable_during_break(client):
    with flask_app.app_context():
        vet = _create_basic_vet()
        schedule = VetSchedule(
            veterinario_id=vet.id,
            dia_semana="Segunda",
            hora_inicio=time(9, 0),
            hora_fim=time(17, 0),
            intervalo_inicio=time(12, 0),
            intervalo_fim=time(13, 0),
        )
        db.session.add(schedule)
        db.session.commit()

        # Exactly during break
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 12, 0)) is False
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 12, 30)) is False

        # Overlaps break (starts at 11:45, ends at 12:15)
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 11, 45)) is False

        # Exactly outside break
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 11, 30)) is True
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 13, 0)) is True


def test_slot_unavailable_due_to_appointment_conflict(client):
    with flask_app.app_context():
        vet = _create_basic_vet()
        tutor, animal = _create_tutor_and_animal(vet.clinica)
        schedule = VetSchedule(
            veterinario_id=vet.id,
            dia_semana="Segunda",
            hora_inicio=time(9, 0),
            hora_fim=time(17, 0),
        )

        # Create an appointment at 10:00 (duration 30min)
        appt_local = datetime(2024, 5, 20, 10, 0, tzinfo=BR_TZ)
        appt_utc = appt_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        appointment = Appointment(
            veterinario_id=vet.id,
            tutor_id=tutor.id,
            animal_id=animal.id,
            clinica_id=vet.clinica.id,
            scheduled_at=appt_utc,
            status="scheduled",
            kind="consulta",
        )
        db.session.add_all([schedule, appointment])
        db.session.commit()

        # Slot conflicts
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 10, 0)) is False

        # Slot overlaps partially
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 9, 45)) is False
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 10, 15)) is False

        # Slot adjacent
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 9, 30)) is True
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 10, 30)) is True


def test_slot_unavailable_due_to_exam_conflict(client):
    with flask_app.app_context():
        vet = _create_basic_vet()
        tutor, animal = _create_tutor_and_animal(vet.clinica)
        schedule = VetSchedule(
            veterinario_id=vet.id,
            dia_semana="Segunda",
            hora_inicio=time(9, 0),
            hora_fim=time(17, 0),
        )

        # Create an exam appointment at 14:00 (duration 30min)
        exam_local = datetime(2024, 5, 20, 14, 0, tzinfo=BR_TZ)
        exam_utc = exam_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        exam = ExamAppointment(
            specialist_id=vet.id,
            requester_id=tutor.id,
            animal_id=animal.id,
            scheduled_at=exam_utc,
            status="confirmed",
        )
        db.session.add_all([schedule, exam])
        db.session.commit()

        assert is_slot_available(vet.id, datetime(2024, 5, 20, 14, 0)) is False
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 13, 30)) is True
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 14, 30)) is True


def test_slot_available_timezone_handling(client):
    with flask_app.app_context():
        vet = _create_basic_vet()
        schedule = VetSchedule(
            veterinario_id=vet.id,
            dia_semana="Segunda",
            hora_inicio=time(9, 0),
            hora_fim=time(17, 0),
        )
        db.session.add(schedule)
        db.session.commit()

        # Naive datetime (interpreted as local time)
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 10, 0)) is True

        # BR_TZ aware datetime
        aware_brt = datetime(2024, 5, 20, 10, 0, tzinfo=BR_TZ)
        assert is_slot_available(vet.id, aware_brt) is True

        # UTC aware datetime - 13:00 UTC is 10:00 BRT
        aware_utc = datetime(2024, 5, 20, 13, 0, tzinfo=ZoneInfo("UTC"))
        assert is_slot_available(vet.id, aware_utc) is True


def test_slot_duration_handling(client):
    with flask_app.app_context():
        vet = _create_basic_vet()

        # Schedule has a break from 12:00 to 13:00
        schedule = VetSchedule(
            veterinario_id=vet.id,
            dia_semana="Segunda",
            hora_inicio=time(9, 0),
            hora_fim=time(17, 0),
            intervalo_inicio=time(12, 0),
            intervalo_fim=time(13, 0),
        )
        db.session.add(schedule)
        db.session.commit()

        # Set a custom duration mapping for the test case
        # assuming 'cirurgia' takes 120 minutes (2 hours)

        # 10:30 to 12:30 overlaps with the 12:00 break
        # We need to temporarily mock `get_appointment_duration` or we can just pass a long duration kind if available
        # The helpers.py gets it from APPOINTMENT_KIND_DURATIONS which we can't easily mock here without monkeypatch,
        # but if we schedule a regular 30m appointment at 11:45, it overlaps the 12:00 break
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 11, 45), kind='consulta') is False

        # Schedule ends at 17:00, so a 30 min slot at 16:45 will end at 17:15, and should be rejected
        assert is_slot_available(vet.id, datetime(2024, 5, 20, 16, 45), kind='consulta') is False
