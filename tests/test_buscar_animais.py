import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from datetime import datetime

from app import app as flask_app, db
from models import User, Clinica, Animal, Appointment, Veterinario


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )

    with flask_app.app_context():
        db.drop_all()
        db.create_all()

    yield flask_app

    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


def login(monkeypatch, user):
    user_id = getattr(user, "id", user)

    def _load_user():
        return User.query.get(user_id)

    monkeypatch.setattr(login_utils, "_get_user", _load_user)


def test_buscar_animais_filters_by_clinic(app, monkeypatch):
    with app.app_context():
        clinic1 = Clinica(nome="Clínica 1")
        clinic2 = Clinica(nome="Clínica 2")
        db.session.add_all([clinic1, clinic2])
        db.session.flush()

        staff = User(
            name="Staff",
            email="staff@example.com",
            password_hash="hash",
            worker="colaborador",
            clinica_id=clinic1.id,
        )
        tutor1 = User(
            name="Tutor Clínica 1",
            email="tutor1@example.com",
            password_hash="hash",
            clinica_id=clinic1.id,
        )
        tutor2 = User(
            name="Tutor Clínica 2",
            email="tutor2@example.com",
            password_hash="hash",
            clinica_id=clinic2.id,
        )
        db.session.add_all([staff, tutor1, tutor2])
        db.session.flush()

        animal1 = Animal(
            name="Paciente Clínica 1",
            user_id=tutor1.id,
            clinica_id=clinic1.id,
        )
        animal2 = Animal(
            name="Paciente Clínica 2",
            user_id=tutor2.id,
            clinica_id=clinic2.id,
        )
        db.session.add_all([animal1, animal2])
        db.session.commit()

        staff_id = staff.id

    login(monkeypatch, staff_id)

    client = app.test_client()
    response = client.get('/buscar_animais?q=Paciente')

    assert response.status_code == 200
    data = response.get_json()
    names = {item['name'] for item in data}

    assert "Paciente Clínica 1" in names
    assert "Paciente Clínica 2" not in names


def test_buscar_animais_without_clinic_returns_empty(app, monkeypatch):
    with app.app_context():
        clinic = Clinica(nome="Clínica 1")
        db.session.add(clinic)
        db.session.flush()

        tutor = User(
            name="Tutor",
            email="tutor@example.com",
            password_hash="hash",
            clinica_id=clinic.id,
        )
        db.session.add(tutor)
        db.session.flush()

        animal = Animal(
            name="Paciente",
            user_id=tutor.id,
            clinica_id=clinic.id,
        )
        guest = User(
            name="Sem Clínica",
            email="guest@example.com",
            password_hash="hash",
            worker="colaborador",
            clinica_id=None,
        )
        db.session.add_all([animal, guest])
        db.session.commit()

        guest_id = guest.id

    login(monkeypatch, guest_id)

    client = app.test_client()
    response = client.get('/buscar_animais?q=Paciente')

    assert response.status_code == 200
    assert response.get_json() == []


def test_buscar_animais_filters_by_tutor_and_returns_metadata(app, monkeypatch):
    with app.app_context():
        clinic = Clinica(nome="Clínica Central")
        db.session.add(clinic)
        db.session.flush()

        staff = User(
            name="Staff",
            email="staff@example.com",
            password_hash="hash",
            worker="colaborador",
            clinica_id=clinic.id,
        )
        tutor1 = User(
            name="Tutor Um",
            email="tutor1@example.com",
            password_hash="hash",
            clinica_id=clinic.id,
        )
        tutor2 = User(
            name="Tutor Dois",
            email="tutor2@example.com",
            password_hash="hash",
            clinica_id=clinic.id,
        )
        vet_user = User(
            name="Dra. Vet",
            email="vet@example.com",
            password_hash="hash",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        db.session.add_all([staff, tutor1, tutor2, vet_user])
        db.session.flush()

        vet_profile = Veterinario(user_id=vet_user.id, crmv="CRMV123", clinica_id=clinic.id)
        db.session.add(vet_profile)
        db.session.flush()

        animal1 = Animal(
            name="Paciente Alfa",
            user_id=tutor1.id,
            clinica_id=clinic.id,
        )
        animal2 = Animal(
            name="Paciente Beta",
            user_id=tutor2.id,
            clinica_id=clinic.id,
        )
        db.session.add_all([animal1, animal2])
        db.session.flush()

        appointment = Appointment(
            animal_id=animal1.id,
            tutor_id=tutor1.id,
            veterinario_id=vet_profile.id,
            scheduled_at=datetime.utcnow(),
            status='scheduled',
            kind='consulta',
            clinica_id=clinic.id,
        )
        db.session.add(appointment)
        db.session.commit()

        staff_id = staff.id
        tutor1_id = tutor1.id
        tutor1_name = tutor1.name
        animal1_id = animal1.id

    login(monkeypatch, staff_id)

    client = app.test_client()
    response = client.get(
        '/buscar_animais',
        query_string={'q': 'Paciente', 'tutor_id': tutor1_id, 'sort': 'recent_attended'},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 1
    record = data[0]

    assert record['id'] == animal1_id
    assert record['tutor_id'] == tutor1_id
    assert record['tutor_name'] == tutor1_name
    assert record['last_appointment']
    assert record['last_appointment_display']
