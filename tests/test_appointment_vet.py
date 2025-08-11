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


def test_veterinarian_can_schedule_for_other_users_animal(client, monkeypatch):
    with flask_app.app_context():
        tutor = User(id=1, name='Tutor', email='tutor@test')
        tutor.set_password('x')
        vet_user = User(id=2, name='Vet', email='vet@test', worker='veterinario')
        vet_user.set_password('x')
        animal = Animal(id=1, name='Rex', user_id=tutor.id)
        plan = HealthPlan(id=1, name='Basic', price=10.0)
        db.session.add_all([tutor, vet_user, animal, plan])
        db.session.commit()
        sub = HealthSubscription(
            animal_id=animal.id, plan_id=plan.id, user_id=tutor.id, active=True
        )
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123')
        schedule = VetSchedule(
            id=1,
            veterinario_id=1,
            dia_semana='Quarta',
            hora_inicio=time(9, 0),
            hora_fim=time(17, 0),
        )
        db.session.add_all([sub, vet, schedule])
        db.session.commit()
        animal_id = animal.id
        vet_id = vet.id
        tutor_id = tutor.id
        vet_user_id = vet_user.id

    fake_vet = type('U', (), {
        'id': vet_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet',
        'is_authenticated': True,
    })()
    login(monkeypatch, fake_vet)
    resp = client.post(
        '/appointments/new',
        data={
            'animal_id': animal_id,
            'veterinario_id': vet_id,
            'date': '2024-05-01',
            'time': '10:00',
            'reason': 'Checkup',
        },
    )
    assert resp.status_code == 302
    with flask_app.app_context():
        appt = Appointment.query.one()
        assert appt.tutor_id == tutor_id
        assert appt.animal_id == animal_id
        assert appt.veterinario_id == vet_id
