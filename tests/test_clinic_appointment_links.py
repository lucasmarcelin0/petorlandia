import os
import sys
import pytest
import flask_login.utils as login_utils
from datetime import datetime

os.environ.setdefault('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db
from models import (
    User,
    Clinica,
    Veterinario,
    Animal,
    Appointment,
    HealthPlan,
    HealthSubscription,
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

def test_clinic_page_has_new_and_edit_links(client, monkeypatch):
    with flask_app.app_context():
        admin = User(name="Admin", email="admin_links@example.com", password_hash="x", role="admin")
        clinic = Clinica(nome="Clinica", owner=admin)
        tutor = User(name="Tutor", email="t@example.com", password_hash="x")
        animal = Animal(name="Rex", owner=tutor, clinica=clinic)
        vet_user = User(name="Vet", email="v@example.com", password_hash="x", worker="veterinario")
        vet = Veterinario(user=vet_user, crmv="123", clinica=clinic)
        plan = HealthPlan(name="Basic", price=10.0)
        db.session.add_all([admin, clinic, tutor, animal, vet_user, vet, plan])
        db.session.commit()
        sub = HealthSubscription(animal_id=animal.id, plan_id=plan.id, user_id=tutor.id, active=True)
        db.session.add(sub)
        db.session.commit()
        appt = Appointment(
            animal_id=animal.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=datetime(2024, 1, 1, 10, 0),
            clinica_id=clinic.id,
        )
        db.session.add(appt)
        db.session.commit()
        appt_id = appt.id
        clinic_id = clinic.id
        admin_id = admin.id
    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(admin_id))
    resp = client.get(f'/clinica/{clinic_id}')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'Novo Agendamento' in html
    assert f'/appointments/{appt_id}/edit' in html
