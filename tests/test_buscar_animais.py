import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils

from app import app as flask_app, db
from datetime import datetime, timedelta

from models import Appointment, Breed, Clinica, Species, Animal, User, Veterinario


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
        species = Species(name="Canina")
        breed = Breed(name="SRD", species=species)
        db.session.add_all([clinic1, clinic2, species, breed])
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
            age="5 anos",
            microchip_number="123",
            user_id=tutor1.id,
            clinica_id=clinic1.id,
            species_id=species.id,
            breed_id=breed.id,
            neutered=True,
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
    response = client.get('/buscar_animais?q=Paciente&sort=name_asc')

    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 1

    animal = data[0]
    assert animal['name'] == "Paciente Clínica 1"
    assert animal['tutor_name'] == "Tutor Clínica 1"
    assert animal['species_name'] == "Canina"
    assert animal['breed_name'] == "SRD"
    assert animal['age_display'] == "5 anos"
    assert animal['microchip_number'] == "123"
    assert animal['last_appointment_at'] is None


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


def test_buscar_animais_filters_by_species_and_status(app, monkeypatch):
    with app.app_context():
        clinic = Clinica(nome="Clínica 1")
        db.session.add(clinic)
        db.session.flush()

        staff = User(
            name="Staff",
            email="staff@example.com",
            password_hash="hash",
            worker="colaborador",
            clinica_id=clinic.id,
        )
        tutor = User(
            name="Tutor",
            email="tutor@example.com",
            password_hash="hash",
            clinica_id=clinic.id,
        )
        species_dog = Species(name="Canina")
        species_cat = Species(name="Felina")
        db.session.add_all([staff, tutor, species_dog, species_cat])
        db.session.flush()

        matching = Animal(
            name="Paciente Alfa",
            user_id=tutor.id,
            clinica_id=clinic.id,
            species_id=species_dog.id,
            status='Internado',
        )
        other = Animal(
            name="Paciente Beta",
            user_id=tutor.id,
            clinica_id=clinic.id,
            species_id=species_cat.id,
            status='disponível',
        )
        db.session.add_all([matching, other])
        db.session.commit()

        staff_id = staff.id
        species_dog_id = species_dog.id
        species_cat_id = species_cat.id

    login(monkeypatch, staff_id)

    client = app.test_client()
    response = client.get(
        f'/buscar_animais?q=Paciente&species_id={species_dog_id}&status=INTERNADO'
    )

    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 1
    assert data[0]['name'] == 'Paciente Alfa'

    response = client.get(
        f'/buscar_animais?q=Paciente&species_id={species_cat_id}&status=INTERNADO'
    )
    assert response.status_code == 200
    assert response.get_json() == []


def test_buscar_animais_supports_sorting_by_recent_attended(app, monkeypatch):
    with app.app_context():
        clinic = Clinica(nome="Clínica 1")
        db.session.add(clinic)
        db.session.flush()

        staff = User(
            name="Staff",
            email="staff@example.com",
            password_hash="hash",
            worker="colaborador",
            clinica_id=clinic.id,
        )
        tutor = User(
            name="Tutor",
            email="tutor@example.com",
            password_hash="hash",
            clinica_id=clinic.id,
        )
        vet_user = User(
            name="Vet",
            email="vet@example.com",
            password_hash="hash",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        db.session.add_all([staff, tutor, vet_user])
        db.session.flush()

        vet = Veterinario(user_id=vet_user.id, crmv="CRMV123", clinica_id=clinic.id)
        db.session.add(vet)
        db.session.flush()

        animal_a = Animal(
            name="Paciente A",
            user_id=tutor.id,
            clinica_id=clinic.id,
        )
        animal_b = Animal(
            name="Paciente B",
            user_id=tutor.id,
            clinica_id=clinic.id,
        )
        db.session.add_all([animal_a, animal_b])
        db.session.flush()

        older = datetime.utcnow() - timedelta(days=2)
        newer = datetime.utcnow() - timedelta(days=1)

        db.session.add_all(
            [
                Appointment(
                    animal_id=animal_a.id,
                    tutor_id=tutor.id,
                    veterinario_id=vet.id,
                    scheduled_at=older,
                    clinica_id=clinic.id,
                ),
                Appointment(
                    animal_id=animal_b.id,
                    tutor_id=tutor.id,
                    veterinario_id=vet.id,
                    scheduled_at=newer,
                    clinica_id=clinic.id,
                ),
            ]
        )
        db.session.commit()

        staff_id = staff.id
        newer_value = newer

    login(monkeypatch, staff_id)

    client = app.test_client()
    response = client.get('/buscar_animais?q=Paciente&sort=recent_attended')

    assert response.status_code == 200
    data = response.get_json()
    assert [item['name'] for item in data][:2] == ["Paciente B", "Paciente A"]

    first_last_at = data[0]['last_appointment_at']
    assert first_last_at is not None
    first_last_dt = datetime.fromisoformat(first_last_at)
    assert first_last_dt.replace(microsecond=0) == newer_value.replace(microsecond=0)


def test_buscar_animais_filters_by_tutor_id(app, monkeypatch):
    with app.app_context():
        clinic = Clinica(nome="Clínica 1")
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
            name="Tutor 1",
            email="tutor1@example.com",
            password_hash="hash",
            clinica_id=clinic.id,
        )
        tutor2 = User(
            name="Tutor 2",
            email="tutor2@example.com",
            password_hash="hash",
            clinica_id=clinic.id,
        )
        db.session.add_all([staff, tutor1, tutor2])
        db.session.flush()

        animal1 = Animal(
            name="Paciente 1",
            user_id=tutor1.id,
            clinica_id=clinic.id,
        )
        animal2 = Animal(
            name="Paciente 2",
            user_id=tutor2.id,
            clinica_id=clinic.id,
        )
        db.session.add_all([animal1, animal2])
        db.session.commit()

        staff_id = staff.id
        tutor1_id = tutor1.id

    login(monkeypatch, staff_id)

    client = app.test_client()
    response = client.get(f'/buscar_animais?q=Paciente&tutor_id={tutor1_id}')

    assert response.status_code == 200
    data = response.get_json()
    assert [item['name'] for item in data] == ["Paciente 1"]
    assert data[0]['tutor_id'] == tutor1_id
