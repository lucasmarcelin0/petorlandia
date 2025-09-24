import os
import sys

import pytest
import flask_login.utils as login_utils

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db
from models import User, Clinica, Veterinario, Animal, VetSchedule, HealthPlan, HealthSubscription, Appointment
from datetime import time, date

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


def setup_data():
    clinic = Clinica(id=1, nome='Clinica')
    tutor = User(id=1, name='Tutor', email='t@test')
    tutor.set_password('x')
    vet_user = User(id=2, name='Vet', email='v@test', worker='veterinario')
    vet_user.set_password('x')
    vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
    animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
    schedule = VetSchedule(veterinario_id=vet.id, dia_semana='Segunda', hora_inicio=time(8,0), hora_fim=time(12,0))
    plan = HealthPlan(id=1, name='Basic', price=10.0)
    sub = HealthSubscription(animal_id=animal.id, plan_id=plan.id, user_id=tutor.id, active=True)
    db.session.add_all([clinic, tutor, vet_user, vet, animal, schedule, plan, sub])
    db.session.commit()
    return clinic.id, animal.id, vet.id


def test_collaborator_can_schedule_consulta(client, monkeypatch):
    with flask_app.app_context():
        clinic_id, animal_id, vet_id = setup_data()
    collaborator = type('U', (), {
        'id': 3,
        'worker': 'colaborador',
        'role': 'adotante',
        'is_authenticated': True,
        'clinica_id': clinic_id,
    })()
    login(monkeypatch, collaborator)
    resp = client.post('/appointments', data={
        'appointment-animal_id': str(animal_id),
        'appointment-veterinario_id': str(vet_id),
        'appointment-date': '2024-05-20',
        'appointment-time': '09:00',
        'appointment-kind': 'consulta',
        'appointment-reason': 'Checkup',
        'appointment-submit': True,
    })
    assert resp.status_code == 302
    with flask_app.app_context():
        appt = Appointment.query.first()
        assert appt is not None
        assert appt.kind == 'consulta'
        assert appt.notes == 'Checkup'
        assert appt.status == 'scheduled'


def test_collaborator_can_schedule_banho_tosa(client, monkeypatch):
    with flask_app.app_context():
        clinic_id, animal_id, vet_id = setup_data()

    collaborator = type('U', (), {
        'id': 4,
        'worker': 'colaborador',
        'role': 'adotante',
        'is_authenticated': True,
        'clinica_id': clinic_id,
    })()
    login(monkeypatch, collaborator)

    resp = client.post('/appointments', data={
        'appointment-animal_id': str(animal_id),
        'appointment-veterinario_id': str(vet_id),
        'appointment-date': '2024-05-20',
        'appointment-time': '10:00',
        'appointment-kind': 'banho_tosa',
        'appointment-reason': 'Spa day',
        'appointment-submit': True,
    })

    assert resp.status_code == 302

    with flask_app.app_context():
        appt = Appointment.query.order_by(Appointment.id.desc()).first()
        assert appt is not None
        assert appt.kind == 'banho_tosa'
        assert appt.notes == 'Spa day'
        assert appt.status == 'scheduled'
