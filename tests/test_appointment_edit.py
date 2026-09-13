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


def test_edit_appointment_shift_overlapping_self_and_seconds_mismatch(client, monkeypatch):
    """Moving 15 min or updating notes when seconds != 0 must not collide with itself."""
    with flask_app.app_context():
        clinic = Clinica(id=10, nome='Clinica10')
        tutor = User(id=10, name='Tutor10', email='tutor10@test')
        tutor.set_password('x')
        vet_user = User(id=20, name='Vet10', email='vet10@test', worker='veterinario')
        vet_user.set_password('x')
        animal = Animal(id=10, name='Max', user_id=tutor.id, clinica_id=clinic.id)
        vet = Veterinario(id=10, user_id=vet_user.id, crmv='777', clinica_id=clinic.id)
        schedule = VetSchedule(id=10, veterinario_id=vet.id, dia_semana='Quinta', hora_inicio=dtime(9,0), hora_fim=dtime(17,0))
        # Scheduled at 11:30:45 (local: 11:30:45 -> UTC: 14:30:45)
        appt = Appointment(
            id=10,
            animal_id=animal.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=datetime(2024, 5, 2, 14, 30, 45),
            clinica_id=clinic.id,
            kind='consulta',
            notes='Initial note'
        )
        db.session.add_all([clinic, tutor, vet_user, animal, vet, schedule, appt])
        db.session.commit()
        appt_id = appt.id
        vet_user_id = vet_user.id
        clinic_id = clinic.id

    fake_vet = type('U', (), {
        'id': vet_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet10',
        'is_authenticated': True,
        'veterinario': type('V', (), {'id': 10, 'clinica_id': clinic_id})()
    })()
    login(monkeypatch, fake_vet)

    # 1. Update only notes with time input '11:30' (seconds 00 vs stored 45)
    resp = client.post(f'/appointments/{appt_id}/edit', json={
        'date': '2024-05-02',
        'time': '11:30',
        'veterinario_id': 10,
        'notes': 'Updated note'
    })
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['success'] is True
    with flask_app.app_context():
        appt = Appointment.query.get(appt_id)
        assert appt.notes == 'Updated note'

    # 2. Shift 15 minutes ahead (11:45), which overlaps the 30-min original slot (11:30 - 12:00)
    resp = client.post(f'/appointments/{appt_id}/edit', json={
        'date': '2024-05-02',
        'time': '11:45',
        'veterinario_id': 10,
        'notes': 'Shifted by 15 min'
    })
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['success'] is True
    with flask_app.app_context():
        appt = Appointment.query.get(appt_id)
        # 11:45 BRT -> 14:45 UTC
        assert appt.scheduled_at == datetime(2024, 5, 2, 14, 45, tzinfo=timezone.utc)


def test_edit_appointment_kind_and_form_encoded(client, monkeypatch):
    """Ensure kind is updated and form-encoded data (data-sync FormData) is supported."""
    with flask_app.app_context():
        clinic = Clinica(id=20, nome='Clinica20')
        tutor = User(id=30, name='Tutor30', email='tutor30@test')
        tutor.set_password('x')
        vet_user = User(id=40, name='Vet30', email='vet30@test', worker='veterinario')
        vet_user.set_password('x')
        animal = Animal(id=30, name='Luna', user_id=tutor.id, clinica_id=clinic.id)
        vet = Veterinario(id=20, user_id=vet_user.id, crmv='888', clinica_id=clinic.id)
        schedule = VetSchedule(id=20, veterinario_id=vet.id, dia_semana='Quinta', hora_inicio=dtime(9,0), hora_fim=dtime(17,0))
        appt = Appointment(
            id=20,
            animal_id=animal.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=datetime(2024, 5, 2, 13, 0),
            clinica_id=clinic.id,
            kind='consulta',
            notes='Consulta de rotina'
        )
        db.session.add_all([clinic, tutor, vet_user, animal, vet, schedule, appt])
        db.session.commit()
        appt_id = appt.id
        vet_user_id = vet_user.id
        clinic_id = clinic.id

    fake_vet = type('U', (), {
        'id': vet_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet30',
        'is_authenticated': True,
        'veterinario': type('V', (), {'id': 20, 'clinica_id': clinic_id})()
    })()
    login(monkeypatch, fake_vet)

    # Submit using form data with Accept: application/json (as data-sync does)
    resp = client.post(
        f'/appointments/{appt_id}/edit',
        data={
            'date': '2024-05-02',
            'time': '10:00',
            'veterinario_id': '20',
            'reason': 'Mudando para retorno',
            'kind': 'retorno',
        },
        headers={'Accept': 'application/json'}
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['success'] is True
    with flask_app.app_context():
        appt = Appointment.query.get(appt_id)
        assert appt.kind == 'retorno'
        assert appt.notes == 'Mudando para retorno'


def test_edit_appointment_prevents_overbooking_with_other_appointment(client, monkeypatch):
    """Ensure conflict with ANOTHER appointment is still strictly blocked with 400."""
    with flask_app.app_context():
        clinic = Clinica(id=30, nome='Clinica30')
        tutor = User(id=50, name='Tutor50', email='tutor50@test')
        tutor.set_password('x')
        vet_user = User(id=60, name='Vet50', email='vet50@test', worker='veterinario')
        vet_user.set_password('x')
        animal1 = Animal(id=40, name='A1', user_id=tutor.id, clinica_id=clinic.id)
        animal2 = Animal(id=41, name='A2', user_id=tutor.id, clinica_id=clinic.id)
        vet = Veterinario(id=30, user_id=vet_user.id, crmv='999', clinica_id=clinic.id)
        schedule = VetSchedule(id=30, veterinario_id=vet.id, dia_semana='Quinta', hora_inicio=dtime(9,0), hora_fim=dtime(17,0))

        # appt1 at 10:00 (local) -> 13:00 UTC
        appt1 = Appointment(
            id=50,
            animal_id=animal1.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=datetime(2024, 5, 2, 13, 0),
            clinica_id=clinic.id,
            kind='consulta'
        )
        # appt2 at 10:30 (local) -> 13:30 UTC
        appt2 = Appointment(
            id=51,
            animal_id=animal2.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=datetime(2024, 5, 2, 13, 30),
            clinica_id=clinic.id,
            kind='consulta'
        )
        db.session.add_all([clinic, tutor, vet_user, animal1, animal2, vet, schedule, appt1, appt2])
        db.session.commit()
        appt1_id = appt1.id
        vet_user_id = vet_user.id
        clinic_id = clinic.id

    fake_vet = type('U', (), {
        'id': vet_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet50',
        'is_authenticated': True,
        'veterinario': type('V', (), {'id': 30, 'clinica_id': clinic_id})()
    })()
    login(monkeypatch, fake_vet)

    # Try to move appt1 to 10:30 (where appt2 already exists!)
    resp = client.post(f'/appointments/{appt1_id}/edit', json={
        'date': '2024-05-02',
        'time': '10:30',
        'veterinario_id': 30,
    })
    assert resp.status_code == 400
    assert resp.get_json()['success'] is False
    assert 'indisponível' in resp.get_json()['message']

    # Also test api_reschedule_appointment
    # 1. Reschedule to overlapping self (10:15) succeeds!
    resp_reschedule = client.post(
        f'/api/appointments/{appt1_id}/reschedule',
        json={'start': '2024-05-02T10:15:00-03:00'}
    )
    # Note: 10:15 overlaps 10:30 (appt2), so 10:15 should be blocked by appt2!
    assert resp_reschedule.status_code == 400

    # Moving appt1 to 09:30 (no conflict with appt2) succeeds!
    resp_ok = client.post(
        f'/api/appointments/{appt1_id}/reschedule',
        json={'start': '2024-05-02T09:30:00-03:00'}
    )
    assert resp_ok.status_code == 200, resp_ok.get_json()
    assert resp_ok.get_json()['success'] is True

