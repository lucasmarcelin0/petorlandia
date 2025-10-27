import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from datetime import datetime, time

from app import app as flask_app, db
from models import (
    User,
    Veterinario,
    VetSchedule,
    Clinica,
    Animal,
    Consulta,
    Appointment,
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


def test_schedule_days_order(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica')
        vet_user = User(id=1, name='Vet', email='vet@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
        s_wed = VetSchedule(
            id=1,
            veterinario_id=vet.id,
            dia_semana='Quarta',
            hora_inicio=time(9, 0),
            hora_fim=time(10, 0),
        )
        s_mon = VetSchedule(
            id=2,
            veterinario_id=vet.id,
            dia_semana='Segunda',
            hora_inicio=time(9, 0),
            hora_fim=time(10, 0),
        )
        db.session.add_all([clinic, vet_user, vet, s_wed, s_mon])
        db.session.commit()
        vet_id = vet.id
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
        })(),
    })()

    login(monkeypatch, fake_vet)
    resp = client.get('/appointments')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert html.index('Segunda') < html.index('Quarta')


def test_finalized_consulta_uses_completion_timestamp(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica')
        vet_user = User(id=1, name='Vet', email='vet@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user=vet_user, crmv='123', clinica_id=clinic.id)

        tutor = User(id=2, name='Tutor', email='tutor@test', worker='adotante', role='adotante')
        tutor.set_password('y')
        animal = Animal(
            id=1,
            name='Buddy',
            status='available',
            user_id=tutor.id,
            clinica_id=clinic.id,
        )

        consulta = Consulta(
            id=1,
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status='finalizada',
            created_at=datetime(2024, 1, 5, 12, 0),
            finalizada_em=datetime(2024, 1, 9, 15, 0),
        )

        appointment = Appointment(
            id=1,
            animal=animal,
            tutor=tutor,
            veterinario=vet,
            scheduled_at=datetime(2023, 12, 30, 10, 0),
            status='completed',
            kind='consulta',
            clinica_id=clinic.id,
            consulta=consulta,
            created_by=vet_user.id,
            created_at=datetime(2023, 12, 1, 10, 0),
        )

        db.session.add_all([clinic, vet_user, vet, tutor, animal, consulta, appointment])
        db.session.commit()
        vet_id = vet.id
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
        })(),
    })()

    login(monkeypatch, fake_vet)
    resp = client.get('/appointments?start=2024-01-08&end=2024-01-14')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'Buddy' in html
    assert '09/01/2024' in html

