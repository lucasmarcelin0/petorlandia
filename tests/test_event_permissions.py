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


def test_appointments_requires_login(client):
    resp = client.get('/appointments')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_non_worker_cannot_create_event(client, monkeypatch):
    with flask_app.app_context():
        user = User(id=1, name='User', email='u@test')
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
    fake_user = type('U', (), {'id':1, 'worker':None, 'role':'adotante', 'is_authenticated':True})()
    login(monkeypatch, fake_user)
    resp = client.post('/appointments', data={'appointment-submit': True})
    assert resp.status_code == 403


def test_collaborator_can_delete_appointment(client, monkeypatch):
    with flask_app.app_context():
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
        clinic_id = clinic.id
        appt = Appointment(id=1, animal_id=animal.id, tutor_id=tutor.id,
                           veterinario_id=vet.id, scheduled_at=datetime.utcnow(),
                           clinica_id=clinic_id)
        db.session.add(appt)
        db.session.commit()
    collaborator = type('U', (), {
        'id': 3,
        'worker': 'colaborador',
        'role': 'adotante',
        'is_authenticated': True,
        'clinica_id': clinic_id,
    })()
    login(monkeypatch, collaborator)
    resp = client.post('/appointments/1/delete', data={})
    assert resp.status_code == 302
    with flask_app.app_context():
        assert Appointment.query.count() == 0
