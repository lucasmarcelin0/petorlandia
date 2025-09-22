import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from app import app as flask_app, db
from helpers import (
    to_timezone_aware,
    get_appointment_duration,
    DEFAULT_VACCINE_EVENT_START_TIME,
    DEFAULT_VACCINE_EVENT_DURATION,
    BR_TZ,
)
from models import (
    User,
    Clinica,
    Animal,
    Veterinario,
    HealthPlan,
    HealthSubscription,
    Appointment,
    ExamAppointment,
    Vacina,
)
from datetime import datetime, timedelta, date

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

def login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)

def create_basic_appointment():
    clinic = Clinica(id=1, nome='Clinica')
    tutor = User(id=1, name='Tutor', email='t@test')
    tutor.set_password('x')
    vet_user = User(id=2, name='Vet', email='v@test', worker='veterinario')
    vet_user.set_password('x')
    vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
    animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
    plan = HealthPlan(id=1, name='Basic', price=10.0)
    sub = HealthSubscription(animal_id=animal.id, plan_id=plan.id, user_id=tutor.id, active=True)
    db.session.add_all([clinic, tutor, vet_user, vet, animal, plan, sub])
    db.session.commit()
    appt = Appointment(id=1, animal_id=animal.id, tutor_id=tutor.id,
                       veterinario_id=vet.id, scheduled_at=datetime(2024,5,1,13,0),
                       clinica_id=clinic.id)
    db.session.add(appt)
    db.session.commit()
    start_iso = to_timezone_aware(appt.scheduled_at).isoformat()
    return tutor.id, vet_user.id, clinic.id, appt.id, start_iso

def test_my_appointments_returns_events(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, clinic_id, appt_id, start_iso = create_basic_appointment()
    fake_user = type('U', (), {'id': tutor_id, 'worker': None, 'role': 'adotante', 'is_authenticated': True})()
    login(monkeypatch, fake_user)
    resp = client.get('/api/my_appointments')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]['id'] == f'appointment-{appt_id}'
    assert data[0]['start'] == start_iso
    assert data[0]['editable'] is True
    assert data[0]['extendedProps']['eventType'] == 'appointment'
    assert data[0]['extendedProps']['recordId'] == appt_id
    start_dt = datetime.fromisoformat(data[0]['start'])
    assert start_dt.tzinfo is not None

def test_clinic_appointments_returns_events(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, clinic_id, appt_id, start_iso = create_basic_appointment()
    fake_vet = type('U', (), {
        'id': vet_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'is_authenticated': True,
        'veterinario': type('V', (), {'id': 1, 'clinica_id': clinic_id})()
    })()
    login(monkeypatch, fake_vet)
    resp = client.get(f'/api/clinic_appointments/{clinic_id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]['id'] == f'appointment-{appt_id}'
    assert data[0]['start'] == start_iso
    assert data[0]['editable'] is True


def test_my_appointments_returns_clinic_events_for_collaborator(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, clinic_id, appt_id, start_iso = create_basic_appointment()
    fake_colab = type('U', (), {
        'id': 3,
        'worker': 'colaborador',
        'role': 'adotante',
        'clinica_id': clinic_id,
        'is_authenticated': True,
    })()
    login(monkeypatch, fake_colab)
    resp = client.get('/api/my_appointments')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]['id'] == f'appointment-{appt_id}'
    assert data[0]['start'] == start_iso


def test_my_appointments_returns_all_for_admin(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, clinic_id, appt_id, start_iso = create_basic_appointment()
    fake_admin = type('U', (), {
        'id': 99,
        'worker': None,
        'role': 'admin',
        'clinica_id': None,
        'is_authenticated': True,
    })()
    login(monkeypatch, fake_admin)
    resp = client.get('/api/my_appointments')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]['id'] == f'appointment-{appt_id}'
    assert data[0]['start'] == start_iso

    user_resp = client.get(f'/api/user_appointments/{tutor_id}')
    assert user_resp.status_code == 200
    user_data = user_resp.get_json()
    assert len(user_data) == 1
    assert user_data[0]['id'] == f'appointment-{appt_id}'
    assert user_data[0]['start'] == start_iso


def test_clinic_appointments_include_exam_and_vaccine(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, clinic_id, appt_id, start_iso = create_basic_appointment()
        animal = Animal.query.get(1)
        vet = Veterinario.query.get(1)
        exam = ExamAppointment(
            id=2,
            animal_id=animal.id,
            specialist_id=vet.id,
            requester_id=tutor_id,
            scheduled_at=datetime(2024, 5, 1, 15, 0),
            status='confirmed',
        )
        vaccine_date = date.today() + timedelta(days=1)
        vaccine = Vacina(
            id=3,
            animal_id=animal.id,
            nome='Raiva',
            aplicada_em=vaccine_date,
            aplicada_por=vet_user_id,
        )
        db.session.add_all([exam, vaccine])
        db.session.commit()

        exam_id = exam.id
        vaccine_id = vaccine.id
        exam_start_iso = to_timezone_aware(exam.scheduled_at).isoformat()
        exam_end_iso = to_timezone_aware(
            exam.scheduled_at + get_appointment_duration('exame')
        ).isoformat()
        vaccine_start = datetime.combine(
            vaccine_date,
            DEFAULT_VACCINE_EVENT_START_TIME,
        ).replace(tzinfo=BR_TZ)
        vaccine_end = vaccine_start + DEFAULT_VACCINE_EVENT_DURATION

    fake_vet = type('U', (), {
        'id': vet_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'is_authenticated': True,
        'veterinario': type('V', (), {'id': 1, 'clinica_id': clinic_id})()
    })()
    login(monkeypatch, fake_vet)
    resp = client.get(f'/api/clinic_appointments/{clinic_id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 3

    events = {event['id']: event for event in data}
    assert f'appointment-{appt_id}' in events
    assert f'exam-{exam_id}' in events
    assert f'vaccine-{vaccine_id}' in events

    exam_event = events[f'exam-{exam_id}']
    assert exam_event['editable'] is False
    assert exam_event['start'] == exam_start_iso
    assert exam_event['end'] == exam_end_iso
    assert exam_event['extendedProps']['eventType'] == 'exam'

    vaccine_event = events[f'vaccine-{vaccine_id}']
    assert vaccine_event['editable'] is False
    assert vaccine_event['start'] == vaccine_start.isoformat()
    assert vaccine_event['end'] == vaccine_end.isoformat()
    assert vaccine_event['extendedProps']['eventType'] == 'vaccine'
