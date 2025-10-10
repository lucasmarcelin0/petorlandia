import os
import sys

import flask_login.utils as login_utils
import pytest


os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


from app import app as flask_app, db  # noqa: E402
from models import (  # noqa: E402
    Animal,
    Appointment,
    Clinica,
    HealthPlan,
    HealthSubscription,
    User,
    Veterinario,
)


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        REQUIRE_HEALTH_SUBSCRIPTION_FOR_APPOINTMENT=False,
    )
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.create_all()
        yield client
        with flask_app.app_context():
            db.drop_all()


def login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def setup_clinic_data():
    clinic = Clinica(id=1, nome='Clínica Principal')
    tutor = User(id=10, name='Tutor', email='tutor@test')
    tutor.set_password('x')
    tutor.clinica_id = clinic.id
    tutor.is_private = False
    animal = Animal(id=11, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
    vet_user = User(id=12, name='Dra. Ana', email='vet@test', worker='veterinario')
    vet_user.set_password('x')
    vet = Veterinario(id=13, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
    plan = HealthPlan(id=20, name='Plano Saúde', price=10.0)
    sub = HealthSubscription(animal_id=animal.id, plan_id=plan.id, user_id=tutor.id, active=True)

    db.session.add_all([clinic, tutor, animal, vet_user, vet, plan, sub])
    db.session.commit()

    return {
        'clinic_id': clinic.id,
        'animal_id': animal.id,
        'vet_id': vet.id,
        'tutor_id': tutor.id,
    }


def collaborator_user(clinic_id):
    return type('U', (), {
        'id': 30,
        'worker': 'colaborador',
        'role': 'adotante',
        'is_authenticated': True,
        'clinica_id': clinic_id,
        'name': 'Colaboradora',
    })()


def test_collaborator_can_schedule_with_autocomplete_ids(client, monkeypatch):
    with flask_app.app_context():
        ids = setup_clinic_data()

    user = collaborator_user(ids['clinic_id'])
    login(monkeypatch, user)

    response = client.get('/buscar_animais', query_string={'q': 'rex'})
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert any(item['id'] == ids['animal_id'] for item in data)

    resp = client.post('/appointments', data={
        'appointment-animal_id': str(ids['animal_id']),
        'appointment-veterinario_id': str(ids['vet_id']),
        'appointment-date': '2024-05-20',
        'appointment-time': '09:00',
        'appointment-kind': 'consulta',
        'appointment-reason': 'Avaliação geral',
        'appointment-submit': True,
    })
    assert resp.status_code == 302

    with flask_app.app_context():
        appointment = Appointment.query.one()
        assert appointment.animal_id == ids['animal_id']
        assert appointment.veterinario_id == ids['vet_id']


def test_collaborator_cannot_schedule_with_foreign_animal(client, monkeypatch):
    with flask_app.app_context():
        ids = setup_clinic_data()
        other_clinic = Clinica(id=2, nome='Outra Clínica')
        other_tutor = User(id=40, name='Outro Tutor', email='outro@test')
        other_tutor.set_password('x')
        other_tutor.clinica_id = other_clinic.id
        other_tutor.is_private = False
        foreign_animal = Animal(id=41, name='Bolt', user_id=other_tutor.id, clinica_id=other_clinic.id)
        db.session.add_all([other_clinic, other_tutor, foreign_animal])
        db.session.commit()
        foreign_animal_id = foreign_animal.id

    user = collaborator_user(ids['clinic_id'])
    login(monkeypatch, user)

    resp = client.post('/appointments', data={
        'appointment-animal_id': str(foreign_animal_id),
        'appointment-veterinario_id': str(ids['vet_id']),
        'appointment-date': '2024-05-21',
        'appointment-time': '09:30',
        'appointment-kind': 'consulta',
        'appointment-reason': 'Tentativa inválida',
        'appointment-submit': True,
    })

    assert resp.status_code == 200

    with flask_app.app_context():
        assert Appointment.query.count() == 0


def test_collaborator_receives_404_when_viewing_foreign_animal_record(client, monkeypatch):
    with flask_app.app_context():
        ids = setup_clinic_data()
        other_clinic = Clinica(id=4, nome='Clínica Externa 404')
        other_tutor = User(id=60, name='Outro Tutor 404', email='outro404@test')
        other_tutor.set_password('x')
        other_tutor.clinica_id = other_clinic.id
        other_tutor.is_private = False
        foreign_animal = Animal(id=61, name='Shadow', user_id=other_tutor.id, clinica_id=other_clinic.id)
        db.session.add_all([other_clinic, other_tutor, foreign_animal])
        db.session.commit()
        foreign_animal_id = foreign_animal.id

    user = collaborator_user(ids['clinic_id'])
    login(monkeypatch, user)

    resp = client.get(f'/animal/{foreign_animal_id}/ficha')
    assert resp.status_code == 404


def test_collaborator_cannot_schedule_with_foreign_veterinarian(client, monkeypatch):
    with flask_app.app_context():
        ids = setup_clinic_data()
        other_clinic = Clinica(id=3, nome='Clínica Externa')
        other_vet_user = User(id=50, name='Dr. Externo', email='externo@test', worker='veterinario')
        other_vet_user.set_password('x')
        external_vet = Veterinario(id=51, user_id=other_vet_user.id, crmv='999', clinica_id=other_clinic.id)
        db.session.add_all([other_clinic, other_vet_user, external_vet])
        db.session.commit()
        external_vet_id = external_vet.id

    user = collaborator_user(ids['clinic_id'])
    login(monkeypatch, user)

    resp = client.post('/appointments', data={
        'appointment-animal_id': str(ids['animal_id']),
        'appointment-veterinario_id': str(external_vet_id),
        'appointment-date': '2024-05-22',
        'appointment-time': '10:00',
        'appointment-kind': 'consulta',
        'appointment-reason': 'Profissional inválido',
        'appointment-submit': True,
    })

    assert resp.status_code == 200

    with flask_app.app_context():
        assert Appointment.query.count() == 0
