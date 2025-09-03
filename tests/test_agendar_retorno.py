import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from datetime import time, datetime
from flask import render_template
from app import app as flask_app, db
from models import (
    User,
    Animal,
    Veterinario,
    Appointment,
    HealthPlan,
    HealthSubscription,
    Clinica,
    Consulta,
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


def test_agendar_retorno_cria_appointment(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica')
        tutor = User(id=1, name='Tutor', email='tutor@test')
        tutor.set_password('x')
        vet_user = User(id=2, name='Vet', email='vet@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
        animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
        consulta = Consulta(id=1, animal_id=animal.id, created_by=vet_user.id, clinica_id=clinic.id, status='finalizada')
        plan = HealthPlan(id=1, name='Basic', price=10.0)
        db.session.add_all([clinic, tutor, vet_user, vet, animal, consulta, plan])
        db.session.commit()
        sub = HealthSubscription(animal_id=animal.id, plan_id=plan.id, user_id=tutor.id, active=True)
        db.session.add(sub)
        db.session.commit()
        consulta_id = consulta.id
        animal_id = animal.id
        tutor_id = tutor.id
        vet_id = vet.id
        clinic_id = clinic.id
        vet_user_id = vet_user.id
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
        f'/agendar_retorno/{consulta_id}',
        data={
            'animal_id': animal_id,
            'veterinario_id': vet_id,
            'date': '2024-05-01',
            'time': '10:00',
            'reason': 'Reavaliação',
        }
    )
    assert resp.status_code == 302
    with flask_app.app_context():
        appt = Appointment.query.one()
        assert appt.consulta_id == consulta_id
        assert appt.animal_id == animal_id
        assert appt.tutor_id == tutor_id
        assert appt.veterinario_id == vet_id


def test_iniciar_retorno_cria_consulta_e_badge(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica')
        tutor = User(id=1, name='Tutor', email='tutor@test')
        tutor.set_password('x')
        vet_user = User(id=2, name='Vet', email='vet@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
        animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
        consulta = Consulta(id=1, animal_id=animal.id, created_by=vet_user.id, clinica_id=clinic.id, status='finalizada')
        appt = Appointment(id=1, animal_id=animal.id, tutor_id=tutor.id, veterinario_id=vet.id, scheduled_at=datetime.utcnow(), consulta_id=consulta.id)
        db.session.add_all([clinic, tutor, vet_user, vet, animal, consulta, appt])
        db.session.commit()
        consulta_id = consulta.id
        animal_id = animal.id
        clinic_id = clinic.id
        vet_user_id = vet_user.id
        vet_id = vet.id
        appt_id = appt.id

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

    resp = client.post(f'/retorno/{appt_id}/start')
    assert resp.status_code == 302

    with flask_app.app_context():
        nova_consulta = Consulta.query.filter_by(retorno_de_id=consulta_id).one()
        assert nova_consulta.animal_id == animal_id
        assert Appointment.query.get(appt_id).status == 'completed'
        nova_consulta.status = 'finalizada'
        db.session.commit()
        animal = Animal.query.get(animal_id)
        html = render_template('partials/historico_consultas.html', animal=animal, historico_consultas=[consulta, nova_consulta])
        assert 'Retorno' in html


def test_finalizar_consulta_sem_confirmacao_quando_retorno_existente(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica')
        tutor = User(id=1, name='Tutor', email='tutor@test')
        tutor.set_password('x')
        vet_user = User(id=2, name='Vet', email='vet@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
        animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
        consulta = Consulta(id=1, animal_id=animal.id, created_by=vet_user.id, clinica_id=clinic.id)
        appt = Appointment(
            id=1,
            consulta_id=consulta.id,
            animal_id=animal.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=datetime.utcnow(),
        )
        db.session.add_all([clinic, tutor, vet_user, vet, animal, consulta, appt])
        db.session.commit()
        consulta_id = consulta.id
        animal_id = animal.id
        clinic_id = clinic.id
        vet_user_id = vet_user.id
        vet_id = vet.id

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
    resp = client.post(f'/finalizar_consulta/{consulta_id}')
    assert resp.status_code == 302
    with flask_app.app_context():
        assert Consulta.query.get(consulta_id).status == 'finalizada'
        assert Appointment.query.count() == 1
