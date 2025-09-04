import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from app import app as flask_app, db
from datetime import time
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
from forms import AppointmentForm


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


def test_veterinarian_can_schedule_for_other_users_animal(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica')
        tutor = User(id=1, name='Tutor', email='tutor@test')
        tutor.set_password('x')
        vet_user = User(id=2, name='Vet', email='vet@test', worker='veterinario')
        vet_user.set_password('x')
        animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
        plan = HealthPlan(id=1, name='Basic', price=10.0)
        db.session.add_all([clinic, tutor, vet_user, animal, plan])
        db.session.commit()
        # ``Veterinario`` is created automatically by the listener
        vet = vet_user.veterinario
        vet.crmv = '123'
        vet.clinica_id = clinic.id
        sub = HealthSubscription(
            animal_id=animal.id, plan_id=plan.id, user_id=tutor.id, active=True
        )
        schedule = VetSchedule(
            id=1,
            veterinario_id=vet.id,
            dia_semana='Quarta',
            hora_inicio=time(9, 0),
            hora_fim=time(17, 0),
        )
        db.session.add_all([sub, schedule])
        db.session.commit()
        animal_id = animal.id
        vet_id = vet.id
        tutor_id = tutor.id
        vet_user_id = vet_user.id
        clinic_id = clinic.id

    fake_vet = type('U', (), {
        'id': vet_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet',
        'is_authenticated': True,
        'veterinario': type('V', (), {
            'id': vet_id,
            'user': type('WU', (), {'name': 'Vet'})(),
            'clinica_id': clinic_id,
        })()
    })()
    login(monkeypatch, fake_vet)
    resp = client.post(
        '/appointments',
        data={
            'appointment-animal_id': animal_id,
            'appointment-veterinario_id': vet_id,
            'appointment-date': '2024-05-01',
            'appointment-time': '10:00',
            'appointment-reason': 'Checkup',
            'appointment-submit': True,
        },
    )
    assert resp.status_code == 302
    with flask_app.app_context():
        appt = Appointment.query.one()
        assert appt.tutor_id == tutor_id
        assert appt.animal_id == animal_id
        assert appt.veterinario_id == vet_id
        assert appt.clinica_id == clinic_id


def test_tutor_sees_only_their_animals_in_form(client):
    with flask_app.app_context():
        tutor1 = User(id=1, name='Tutor1', email='t1@test')
        tutor1.set_password('x')
        tutor2 = User(id=2, name='Tutor2', email='t2@test')
        tutor2.set_password('x')
        animal1 = Animal(id=1, name='Rex', user_id=tutor1.id)
        animal2 = Animal(id=2, name='Fido', user_id=tutor2.id)
        db.session.add_all([tutor1, tutor2, animal1, animal2])
        db.session.commit()
        form = AppointmentForm(tutor=tutor1)
        assert (animal1.id, animal1.name) in form.animal_id.choices
        assert (animal2.id, animal2.name) not in form.animal_id.choices


def test_veterinarian_sees_all_animals_in_form(client):
    with flask_app.app_context():
        tutor1 = User(id=1, name='Tutor1', email='t1@test')
        tutor1.set_password('x')
        tutor2 = User(id=2, name='Tutor2', email='t2@test')
        tutor2.set_password('x')
        animal1 = Animal(id=1, name='Rex', user_id=tutor1.id)
        animal2 = Animal(id=2, name='Fido', user_id=tutor2.id)
        vet_user = User(id=3, name='Vet', email='vet@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123')
        db.session.add_all([tutor1, tutor2, animal1, animal2, vet_user, vet])
        db.session.commit()
        form = AppointmentForm(is_veterinario=True)
        assert (animal1.id, animal1.name) in form.animal_id.choices
        assert (animal2.id, animal2.name) in form.animal_id.choices
