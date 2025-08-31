import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from app import app as flask_app, db
from models import User, Appointment, Clinica, Animal, Veterinario, HealthPlan, HealthSubscription
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


def create_data():
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
                       veterinario_id=vet.id, scheduled_at=datetime(2025, 1, 1, 9, 0),
                       clinica_id=clinic.id)
    db.session.add(appt)
    db.session.commit()


def test_clinic_appointments_api(client, monkeypatch):
    with flask_app.app_context():
        create_data()
    login(monkeypatch, type('U', (), {'id': 2, 'worker': 'veterinario',
                                      'role': 'adotante', 'is_authenticated': True,
                                      'veterinario': type('V', (), {'id':1, 'clinica_id':1})()})())
    resp = client.get('/api/clinic_appointments/1')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]['title'] == 'Rex'


def test_my_appointments_api_for_vet(client, monkeypatch):
    with flask_app.app_context():
        create_data()
    login(monkeypatch, type('U', (), {'id': 2, 'worker': 'veterinario',
                                      'role': 'adotante', 'is_authenticated': True,
                                      'veterinario': type('V', (), {'id':1, 'clinica_id':1})()})())
    resp = client.get('/api/my_appointments')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data[0]['title'] == 'Rex'
