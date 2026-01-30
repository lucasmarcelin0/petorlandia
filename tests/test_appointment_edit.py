import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from app import app as flask_app, db
from datetime import datetime, time as dtime, timezone
from models import (
    User,
    Animal,
    Veterinario,
    Appointment,
    HealthPlan,
    HealthSubscription,
    VetSchedule,
    Clinica,
)


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


def test_vet_can_edit_appointment_date_time_and_vet(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica')
        tutor = User(id=1, name='Tutor', email='tutor@test')
        tutor.set_password('x')
        vet_user1 = User(id=2, name='Vet1', email='vet1@test', worker='veterinario')
        vet_user1.set_password('x')
        vet_user2 = User(id=3, name='Vet2', email='vet2@test', worker='veterinario')
        vet_user2.set_password('x')
        animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
        plan = HealthPlan(id=1, name='Basic', price=10.0)
        sub = HealthSubscription(animal_id=animal.id, plan_id=plan.id, user_id=tutor.id, active=True)
        vet1 = Veterinario(id=1, user_id=vet_user1.id, crmv='123', clinica_id=clinic.id)
        vet2 = Veterinario(id=2, user_id=vet_user2.id, crmv='456', clinica_id=clinic.id)
        schedule1 = VetSchedule(id=1, veterinario_id=vet1.id, dia_semana='Quinta', hora_inicio=dtime(9,0), hora_fim=dtime(17,0))
        schedule2 = VetSchedule(id=2, veterinario_id=vet2.id, dia_semana='Quinta', hora_inicio=dtime(9,0), hora_fim=dtime(17,0))
        db.session.add_all([clinic, tutor, vet_user1, vet_user2, animal, plan, sub, vet1, vet2, schedule1, schedule2])
        db.session.commit()
        appt = Appointment(id=1, animal_id=animal.id, tutor_id=tutor.id, veterinario_id=vet1.id, scheduled_at=datetime(2024,5,1,13,0), clinica_id=clinic.id)
        db.session.add(appt)
        db.session.commit()
        appt_id = appt.id
        vet1_user_id = vet_user1.id
        clinic_id = clinic.id
    fake_vet = type('U', (), {
        'id': vet1_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet1',
        'is_authenticated': True,
        'veterinario': type('V', (), {'id': 1, 'clinica_id': clinic_id})()
    })()
    login(monkeypatch, fake_vet)
    resp = client.post(f'/appointments/{appt_id}/edit', json={
        'date': '2024-05-02',
        'time': '11:30',
        'veterinario_id': 2,
        'notes': 'Trazer exames'
    })
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    with flask_app.app_context():
        appt = Appointment.query.get(appt_id)
        assert appt.veterinario_id == 2
        assert appt.scheduled_at == datetime(2024,5,2,14,30, tzinfo=timezone.utc)
        assert appt.notes == 'Trazer exames'


def test_vet_can_edit_appointment_missing_clinic_id(client, monkeypatch):
    """Ensure vets can edit legacy appointments without clinic ID."""
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica')
        tutor = User(id=1, name='Tutor', email='tutor@test')
        tutor.set_password('x')
        vet_user1 = User(id=2, name='Vet1', email='vet1@test', worker='veterinario')
        vet_user1.set_password('x')
        vet_user2 = User(id=3, name='Vet2', email='vet2@test', worker='veterinario')
        vet_user2.set_password('x')
        animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
        plan = HealthPlan(id=1, name='Basic', price=10.0)
        sub = HealthSubscription(animal_id=animal.id, plan_id=plan.id, user_id=tutor.id, active=True)
        vet1 = Veterinario(id=1, user_id=vet_user1.id, crmv='123', clinica_id=clinic.id)
        vet2 = Veterinario(id=2, user_id=vet_user2.id, crmv='456', clinica_id=clinic.id)
        schedule1 = VetSchedule(id=1, veterinario_id=vet1.id, dia_semana='Quinta', hora_inicio=dtime(9,0), hora_fim=dtime(17,0))
        schedule2 = VetSchedule(id=2, veterinario_id=vet2.id, dia_semana='Quinta', hora_inicio=dtime(9,0), hora_fim=dtime(17,0))
        db.session.add_all([clinic, tutor, vet_user1, vet_user2, animal, plan, sub, vet1, vet2, schedule1, schedule2])
        db.session.commit()
        appt = Appointment(id=1, animal_id=animal.id, tutor_id=tutor.id, veterinario_id=vet1.id, scheduled_at=datetime(2024,5,1,13,0))
        db.session.add(appt)
        db.session.commit()
        # Simulate legacy data with missing clinica_id
        db.session.execute(db.text('UPDATE appointment SET clinica_id=NULL WHERE id=:id'), {'id': appt.id})
        db.session.commit()
        appt_id = appt.id
        vet1_user_id = vet_user1.id
        clinic_id = clinic.id
    fake_vet = type('U', (), {
        'id': vet1_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet1',
        'is_authenticated': True,
        'veterinario': type('V', (), {'id': 1, 'clinica_id': clinic_id})()
    })()
    login(monkeypatch, fake_vet)
    resp = client.post(f'/appointments/{appt_id}/edit', json={
        'date': '2024-05-02',
        'time': '11:30',
        'veterinario_id': 2,
        'notes': 'Trazer exames'
    })
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    with flask_app.app_context():
        appt = Appointment.query.get(appt_id)
        assert appt.veterinario_id == 2
        assert appt.scheduled_at == datetime(2024,5,2,14,30, tzinfo=timezone.utc)
