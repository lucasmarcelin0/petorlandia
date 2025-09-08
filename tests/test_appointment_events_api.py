import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from routes.app import app as flask_app, db
from models import User, Clinica, Animal, Veterinario, HealthPlan, HealthSubscription, Appointment
from datetime import datetime

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
    return tutor.id, vet_user.id, clinic.id, appt.id, appt.scheduled_at.isoformat()

def test_my_appointments_returns_events(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, clinic_id, appt_id, start_iso = create_basic_appointment()
    fake_user = type('U', (), {'id': tutor_id, 'worker': None, 'role': 'adotante', 'is_authenticated': True})()
    login(monkeypatch, fake_user)
    resp = client.get('/api/my_appointments')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]['id'] == appt_id
    assert data[0]['start'] == start_iso

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
    assert data[0]['id'] == appt_id


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
    assert data[0]['id'] == appt_id


def test_my_appointments_returns_all_for_admin(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, clinic_id, appt_id, start_iso = create_basic_appointment()
    fake_admin = type('U', (), {
        'id': 99,
        'worker': None,
        'role': 'admin',
        'is_authenticated': True,
    })()
    login(monkeypatch, fake_admin)
    resp = client.get('/api/my_appointments')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]['id'] == appt_id
