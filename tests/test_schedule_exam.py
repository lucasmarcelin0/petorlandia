import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from app import app as flask_app, db
from models import User, Clinica, Animal, Veterinario, Specialty, VetSchedule, ExamAppointment, AgendaEvento
from datetime import datetime, time, date
from helpers import get_available_times


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


def setup_data():
    clinic = Clinica(nome='Clinica')
    tutor = User(name='Tutor', email='t@test')
    tutor.set_password('x')
    vet_user = User(name='Vet', email='v@test', worker='veterinario')
    vet_user.set_password('x')
    vet = Veterinario(user=vet_user, crmv='123', clinica=clinic)
    spec = Specialty(nome='Raio-X')
    vet.specialties.append(spec)
    schedule = VetSchedule(veterinario=vet, dia_semana='Segunda', hora_inicio=time(9,0), hora_fim=time(17,0))
    animal = Animal(name='Rex', owner=tutor, clinica=clinic)
    db.session.add_all([clinic, tutor, vet_user, vet, spec, schedule, animal])
    db.session.commit()
    return tutor.id, vet_user.id, animal.id, vet.id


def test_schedule_exam_creates_event_and_blocks_time(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, animal_id, vet_id = setup_data()
    fake_user = type('U', (), {'id': tutor_id, 'worker': None, 'role': 'adotante', 'is_authenticated': True})()
    login(monkeypatch, fake_user)
    resp = client.post(f'/animal/{animal_id}/schedule_exam', json={
        'specialist_id': vet_id,
        'date': '2024-05-20',
        'time': '09:00'
    }, headers={'Accept': 'application/json'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success']
    with flask_app.app_context():
        assert ExamAppointment.query.count() == 1
        assert AgendaEvento.query.count() == 1
        times = get_available_times(vet_id, date(2024,5,20))
        assert '09:00' not in times
