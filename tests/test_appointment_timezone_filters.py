import os
import sys
from datetime import datetime, timezone

import flask_login.utils as login_utils
import pytest


os.environ.setdefault('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db
from helpers import BR_TZ
from models import Animal, Appointment, Clinica, User, Veterinario


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SECRET_KEY='testing',
    )
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.create_all()
        yield client
        with flask_app.app_context():
            db.drop_all()


def _local_naive_to_utc(local_dt: datetime) -> datetime:
    return local_dt.replace(tzinfo=BR_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def test_late_brt_appointment_survives_local_filters(client, monkeypatch):
    with flask_app.app_context():
        admin = User(name='Admin', email='admin@example.com', password_hash='x', role='admin')
        clinic = Clinica(nome='Clínica Teste', owner=admin)
        tutor = User(name='Tutor', email='tutor@example.com', password_hash='x')
        vet_user = User(
            name='Vet',
            email='vet@example.com',
            password_hash='x',
            worker='veterinario',
        )
        vet = Veterinario(user=vet_user, crmv='123', clinica=clinic)
        animal = Animal(name='Rex', owner=tutor, clinica=clinic)
        db.session.add_all([admin, clinic, tutor, vet_user, vet, animal])
        db.session.commit()

        scheduled_local = datetime(2024, 5, 1, 23, 30)
        scheduled_utc = _local_naive_to_utc(scheduled_local)
        appointment = Appointment(
            animal_id=animal.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=scheduled_utc,
            clinica_id=clinic.id,
            status='accepted',
            kind='consulta',
        )
        db.session.add(appointment)
        db.session.commit()

        vet_user_id = vet_user.id
        admin_id = admin.id
        clinic_id = clinic.id

    start = '2024-05-01'

    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(vet_user_id))
    resp = client.get(f'/appointments?start={start}&end={start}')
    assert resp.status_code == 200
    vet_html = resp.data.decode()
    assert '01/05/2024 23:30' in vet_html

    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(admin_id))
    resp = client.get(f'/clinica/{clinic_id}?start={start}&end={start}')
    assert resp.status_code == 200
    clinic_html = resp.data.decode()
    assert '23:30' in clinic_html
    assert 'Rex' in clinic_html
