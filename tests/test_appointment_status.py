import pytest
import flask_login.utils as login_utils
from datetime import datetime, timedelta

from routes.app import app as flask_app, db
from models import User, Clinica, Veterinario, Animal, Appointment, HealthPlan, HealthSubscription


@pytest.fixture
def client():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.create_all()
        yield client
        with flask_app.app_context():
            db.drop_all()


def login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def _setup_data():
    clinic = Clinica(id=1, nome="Clinica")
    tutor = User(id=1, name="Tutor", email="t@test")
    tutor.set_password("x")
    vet_user = User(id=2, name="Vet", email="v@test", worker="veterinario")
    vet_user.set_password("x")
    vet = Veterinario(id=1, user_id=vet_user.id, crmv="123", clinica_id=clinic.id)
    animal = Animal(id=1, name="Rex", user_id=tutor.id, clinica_id=clinic.id)
    plan = HealthPlan(id=1, name="Basic", price=10.0)
    sub = HealthSubscription(animal_id=animal.id, plan_id=plan.id, user_id=tutor.id, active=True)
    db.session.add_all([clinic, tutor, vet_user, vet, animal, plan, sub])
    db.session.commit()
    appt = Appointment(
        id=1,
        animal_id=animal.id,
        tutor_id=tutor.id,
        veterinario_id=vet.id,
        scheduled_at=datetime.utcnow() + timedelta(hours=3),
        clinica_id=clinic.id,
    )
    db.session.add(appt)
    db.session.commit()
    return appt.id, clinic.id


def test_update_status_and_delete(client, monkeypatch):
    with flask_app.app_context():
        appt_id, clinic_id = _setup_data()
    user = type('U', (), {
        'id': 99,
        'worker': 'colaborador',
        'role': 'adotante',
        'is_authenticated': True,
        'clinica_id': clinic_id,
    })()
    login(monkeypatch, user)
    resp = client.post(f'/appointments/{appt_id}/status', data={'status': 'completed'})
    assert resp.status_code == 302
    with flask_app.app_context():
        appt = Appointment.query.get(appt_id)
        assert appt.status == 'completed'
    resp = client.post(f'/appointments/{appt_id}/status', data={'status': 'canceled'})
    assert resp.status_code == 302
    with flask_app.app_context():
        appt = Appointment.query.get(appt_id)
        assert appt.status == 'canceled'
    resp = client.post(f'/appointments/{appt_id}/delete', data={})
    assert resp.status_code == 302
    with flask_app.app_context():
        assert Appointment.query.get(appt_id) is None
