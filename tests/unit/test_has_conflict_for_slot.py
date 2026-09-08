import pytest
from datetime import datetime, timedelta
from app import app as flask_app, db
from models import User, Veterinario, Animal
from models.agenda import Appointment, ExamAppointment
from helpers import has_conflict_for_slot
from time_utils import BR_TZ


@pytest.fixture
def app_context():
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:'
    )
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def vet_user(app_context):
    user = User(name="Vet", email="vet@example.com", password_hash="x", worker="veterinario")
    vet = Veterinario(user=user, crmv="123")
    db.session.add(user)
    db.session.add(vet)
    db.session.commit()
    return vet


@pytest.fixture
def animal(app_context):
    owner = User(name="Tutor", email="tutor@example.com", password_hash="x")
    anim = Animal(name="Rex", owner=owner)
    db.session.add(owner)
    db.session.add(anim)
    db.session.commit()
    return anim


def test_has_conflict_empty(vet_user):
    start = datetime(2023, 10, 10, 10, 0)
    duration = timedelta(minutes=30)
    assert not has_conflict_for_slot(vet_user.id, start, duration)


def test_has_conflict_with_appointment(vet_user, animal):
    start = datetime(2023, 10, 10, 10, 0, tzinfo=BR_TZ)
    duration = timedelta(minutes=30)

    appt = Appointment(
        veterinario_id=vet_user.id,
        animal_id=animal.id,
        tutor_id=animal.owner.id,
        scheduled_at=start,
        kind="consulta"
    )
    db.session.add(appt)
    db.session.commit()

    assert has_conflict_for_slot(vet_user.id, datetime(2023, 10, 10, 10, 0), duration)
    assert has_conflict_for_slot(vet_user.id, datetime(2023, 10, 10, 10, 15), duration)
    assert has_conflict_for_slot(vet_user.id, datetime(2023, 10, 10, 9, 45), duration)
    assert not has_conflict_for_slot(vet_user.id, datetime(2023, 10, 10, 9, 30), duration)
    assert not has_conflict_for_slot(vet_user.id, datetime(2023, 10, 10, 10, 30), duration)


def test_has_conflict_with_exam(vet_user, animal):
    start = datetime(2023, 10, 10, 10, 0, tzinfo=BR_TZ)
    duration = timedelta(minutes=30)

    exam = ExamAppointment(
        specialist_id=vet_user.id,
        animal_id=animal.id,
        requester_id=animal.owner.id,
        scheduled_at=start,
    )
    db.session.add(exam)
    db.session.commit()

    assert has_conflict_for_slot(vet_user.id, datetime(2023, 10, 10, 10, 15), duration)


def test_has_conflict_exclude_appointment(vet_user, animal):
    start = datetime(2023, 10, 10, 10, 0, tzinfo=BR_TZ)
    duration = timedelta(minutes=30)

    appt = Appointment(
        veterinario_id=vet_user.id,
        animal_id=animal.id,
        tutor_id=animal.owner.id,
        scheduled_at=start,
        kind="consulta"
    )
    db.session.add(appt)
    db.session.commit()

    assert has_conflict_for_slot(vet_user.id, datetime(2023, 10, 10, 10, 0), duration)
    assert not has_conflict_for_slot(
        vet_user.id,
        datetime(2023, 10, 10, 10, 0),
        duration,
        exclude_appointment_id=appt.id
    )


def test_has_conflict_exclude_exam(vet_user, animal):
    start = datetime(2023, 10, 10, 10, 0, tzinfo=BR_TZ)
    duration = timedelta(minutes=30)

    exam = ExamAppointment(
        specialist_id=vet_user.id,
        animal_id=animal.id,
        requester_id=animal.owner.id,
        scheduled_at=start,
    )
    db.session.add(exam)
    db.session.commit()

    assert not has_conflict_for_slot(
        vet_user.id,
        datetime(2023, 10, 10, 10, 0),
        duration,
        exclude_exam_id=exam.id
    )


def test_has_conflict_preloaded(vet_user, animal):
    start = datetime(2023, 10, 10, 10, 0, tzinfo=BR_TZ)
    duration = timedelta(minutes=30)

    appt = Appointment(
        id=999,
        veterinario_id=vet_user.id,
        animal_id=animal.id,
        tutor_id=animal.owner.id,
        scheduled_at=start,
        kind="consulta"
    )

    exam = ExamAppointment(
        id=888,
        specialist_id=vet_user.id,
        animal_id=animal.id,
        requester_id=animal.owner.id,
        scheduled_at=datetime(2023, 10, 10, 14, 0, tzinfo=BR_TZ),
    )

    preloaded_appts = {appt.id: appt}
    preloaded_exams = {exam.id: exam}

    assert has_conflict_for_slot(
        vet_user.id,
        datetime(2023, 10, 10, 10, 15),
        duration,
        preloaded_appointments=preloaded_appts,
        preloaded_exams=preloaded_exams
    )
    assert has_conflict_for_slot(
        vet_user.id,
        datetime(2023, 10, 10, 14, 15),
        duration,
        preloaded_appointments=preloaded_appts,
        preloaded_exams=preloaded_exams
    )
    assert not has_conflict_for_slot(
        vet_user.id,
        datetime(2023, 10, 10, 12, 0),
        duration,
        preloaded_appointments=preloaded_appts,
        preloaded_exams=preloaded_exams
    )
