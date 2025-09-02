import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from app import app as flask_app, db
from models import User, Clinica, Animal, Veterinario, Specialty, VetSchedule, ExamAppointment, AgendaEvento, Message
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
    fake_user = type('U', (), {'id': tutor_id, 'worker': None, 'role': 'adotante', 'is_authenticated': True, 'name': 'Tutor'})()
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


def test_schedule_exam_message_and_confirm_by(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, animal_id, vet_id = setup_data()
    fake_user = type('U', (), {'id': tutor_id, 'worker': None, 'role': 'adotante', 'is_authenticated': True, 'name': 'Tutor'})()
    login(monkeypatch, fake_user)
    resp = client.post(f'/animal/{animal_id}/schedule_exam', json={
        'specialist_id': vet_id,
        'date': '2024-05-21',
        'time': '09:00'
    }, headers={'Accept': 'application/json'})
    assert resp.status_code == 200
    with flask_app.app_context():
        appt = ExamAppointment.query.first()
        assert pytest.approx((appt.confirm_by - appt.request_time).total_seconds(), rel=1e-3) == 7200
        msg = Message.query.filter_by(receiver_id=vet_user_id).first()
        assert msg is not None
        assert 'Confirme' in msg.content


def test_update_exam_appointment_changes_time(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, animal_id, vet_id = setup_data()
    fake_user = type('U', (), {'id': tutor_id, 'worker': None, 'role': 'adotante', 'is_authenticated': True, 'name': 'Tutor'})()
    login(monkeypatch, fake_user)
    client.post(f'/animal/{animal_id}/schedule_exam', json={
        'specialist_id': vet_id,
        'date': '2024-05-22',
        'time': '09:00'
    }, headers={'Accept': 'application/json'})
    resp = client.post('/exam_appointment/1/update', json={'date': '2024-05-22', 'time': '10:00'}, headers={'Accept': 'application/json'})
    assert resp.status_code == 200
    with flask_app.app_context():
        appt = ExamAppointment.query.get(1)
        assert appt.scheduled_at == datetime(2024, 5, 22, 13, 0)


def test_delete_exam_appointment_removes_record(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, animal_id, vet_id = setup_data()
    fake_user = type('U', (), {'id': tutor_id, 'worker': None, 'role': 'adotante', 'is_authenticated': True, 'name': 'Tutor'})()
    login(monkeypatch, fake_user)
    client.post(f'/animal/{animal_id}/schedule_exam', json={
        'specialist_id': vet_id,
        'date': '2024-05-23',
        'time': '09:00'
    }, headers={'Accept': 'application/json'})
    resp = client.post('/exam_appointment/1/delete', headers={'Accept': 'application/json'})
    assert resp.status_code == 200
    with flask_app.app_context():
        assert ExamAppointment.query.count() == 0


def test_exam_appointments_listed_on_page(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, animal_id, vet_id = setup_data()
    fake_user = type('U', (), {'id': tutor_id, 'worker': None, 'role': 'adotante', 'is_authenticated': True, 'name': 'Tutor'})()
    login(monkeypatch, fake_user)
    client.post(
        f'/animal/{animal_id}/schedule_exam',
        json={'specialist_id': vet_id, 'date': '2024-05-20', 'time': '09:00'},
        headers={'Accept': 'application/json'}
    )
    resp = client.get('/appointments')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Agenda de Exames' in html
    assert '09:00' in html
    assert 'Vet' in html


def test_exam_appointment_requires_acceptance(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, animal_id, vet_id = setup_data()
        vet_obj = Veterinario.query.get(vet_id)
    # schedule exam as tutor
    tutor_user = type('U', (), {'id': tutor_id, 'worker': None, 'role': 'adotante', 'is_authenticated': True, 'name': 'Tutor'})()
    login(monkeypatch, tutor_user)
    client.post(
        f'/animal/{animal_id}/schedule_exam',
        json={'specialist_id': vet_id, 'date': '2024-05-20', 'time': '09:00'},
        headers={'Accept': 'application/json'}
    )
    with flask_app.app_context():
        appt = ExamAppointment.query.first()
        assert appt.status == 'pending'
    # now login as specialist and accept
    vet_user = type('U', (), {'id': vet_user_id, 'worker': 'veterinario', 'role': None, 'is_authenticated': True, 'name': 'Vet', 'veterinario': vet_obj})()
    login(monkeypatch, vet_user)
    resp = client.post('/exam_appointment/1/status', json={'status': 'confirmed'}, headers={'Accept': 'application/json'})
    assert resp.status_code == 200
    with flask_app.app_context():
        appt = ExamAppointment.query.get(1)
        assert appt.status == 'confirmed'
        msg = Message.query.filter_by(receiver_id=tutor_id).first()
        assert msg is not None
        assert '20/05/2024 09:00' in msg.content
        assert 'Vet' in msg.content


def test_schedule_exam_same_user_auto_confirms(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, animal_id, vet_id = setup_data()
    vet_user = type(
        'U',
        (),
        {
            'id': vet_user_id,
            'worker': 'veterinario',
            'role': None,
            'is_authenticated': True,
            'name': 'Vet'
        }
    )()
    login(monkeypatch, vet_user)
    resp = client.post(
        f'/animal/{animal_id}/schedule_exam',
        json={'specialist_id': vet_id, 'date': '2024-05-24', 'time': '09:00'},
        headers={'Accept': 'application/json'}
    )
    assert resp.status_code == 200
    with flask_app.app_context():
        appt = ExamAppointment.query.first()
        assert appt.status == 'confirmed'
        assert Message.query.count() == 0


def test_schedule_exam_blocks_overlapping_time(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, animal_id, vet_id = setup_data()
    fake_user = type('U', (), {'id': tutor_id, 'worker': None, 'role': 'adotante', 'is_authenticated': True, 'name': 'Tutor'})()
    login(monkeypatch, fake_user)
    client.post(
        f'/animal/{animal_id}/schedule_exam',
        json={'specialist_id': vet_id, 'date': '2024-05-25', 'time': '09:00'},
        headers={'Accept': 'application/json'}
    )
    resp = client.post(
        f'/animal/{animal_id}/schedule_exam',
        json={'specialist_id': vet_id, 'date': '2024-05-25', 'time': '09:15'},
        headers={'Accept': 'application/json'}
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert not data['success']


def test_update_exam_appointment_blocks_overlap(client, monkeypatch):
    with flask_app.app_context():
        tutor_id, vet_user_id, animal_id, vet_id = setup_data()
    fake_user = type('U', (), {'id': tutor_id, 'worker': None, 'role': 'adotante', 'is_authenticated': True, 'name': 'Tutor'})()
    login(monkeypatch, fake_user)
    client.post(
        f'/animal/{animal_id}/schedule_exam',
        json={'specialist_id': vet_id, 'date': '2024-05-26', 'time': '09:00'},
        headers={'Accept': 'application/json'}
    )
    client.post(
        f'/animal/{animal_id}/schedule_exam',
        json={'specialist_id': vet_id, 'date': '2024-05-26', 'time': '10:00'},
        headers={'Accept': 'application/json'}
    )
    resp = client.post(
        '/exam_appointment/2/update',
        json={'date': '2024-05-26', 'time': '09:15'},
        headers={'Accept': 'application/json'}
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert not data['success']
