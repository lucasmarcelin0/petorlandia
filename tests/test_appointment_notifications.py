import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from datetime import datetime, timedelta
from routes.app import app as flask_app, db
from models import User, Clinica, Animal, Veterinario, HealthPlan, HealthSubscription, Appointment


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


def create_base_data(hours_ahead):
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
    appt = Appointment(
        id=1,
        animal_id=animal.id,
        tutor_id=tutor.id,
        veterinario_id=vet.id,
        scheduled_at=datetime.utcnow() + timedelta(hours=hours_ahead),
        clinica_id=clinic.id,
    )
    db.session.add(appt)
    db.session.commit()
    return vet_user.id, vet.id, appt.id


def test_pending_page_allows_accept(client, monkeypatch):
    with flask_app.app_context():
        vet_user_id, vet_id, appt_id = create_base_data(3)
    fake_vet = type('U', (), {
        'id': vet_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet',
        'is_authenticated': True,
        'veterinario': type('V', (), {'id': vet_id, 'clinica_id': 1, 'user': type('UU', (), {'name': 'Vet'})()})()
    })()
    login(monkeypatch, fake_vet)
    resp = client.get('/appointments')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Aceitar' in html
    assert 'Tempo restante' in html
    resp = client.post(f'/appointments/{appt_id}/status', data={'status': 'accepted'})
    assert resp.status_code == 302
    with flask_app.app_context():
        assert Appointment.query.get(appt_id).status == 'accepted'
    resp = client.get('/appointments')
    html = resp.get_data(as_text=True)
    assert 'Aceitar' not in html
    assert 'Rex' in html


def test_cannot_accept_within_two_hours(client, monkeypatch):
    with flask_app.app_context():
        vet_user_id, vet_id, appt_id = create_base_data(1)
    fake_vet = type('U', (), {
        'id': vet_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet',
        'is_authenticated': True,
        'veterinario': type('V', (), {'id': vet_id, 'clinica_id': 1})()
    })()
    login(monkeypatch, fake_vet)
    resp = client.post(f'/appointments/{appt_id}/status', data={'status': 'accepted'})
    assert resp.status_code == 400
    with flask_app.app_context():
        assert Appointment.query.get(appt_id).status == 'scheduled'
