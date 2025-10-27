import os
import sys
from datetime import datetime, timedelta

import pytest

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db, _get_recent_animais, _get_recent_tutores  # noqa: E402
from models import Appointment, Animal, Clinica, User, Veterinario  # noqa: E402


@pytest.fixture
def app_context():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def _create_tutor(name: str, email: str, clinic: Clinica) -> User:
    tutor = User(
        name=name,
        email=email,
        password_hash="hash",
        is_private=False,
    )
    tutor.clinica = clinic
    return tutor


def test_specialist_recent_lists_filtered_by_veterinarian(app_context):
    now = datetime.utcnow()
    clinic = Clinica(nome="Shared Clinic")

    vet_user = User(
        name="Specialist",
        email="specialist@example.com",
        password_hash="hash",
        role="veterinario",
        worker="veterinario",
        is_private=False,
    )
    other_vet_user = User(
        name="Generalist",
        email="generalist@example.com",
        password_hash="hash",
        role="veterinario",
        worker="veterinario",
        is_private=False,
    )

    vet = Veterinario(user=vet_user, crmv="12345")
    other_vet = Veterinario(user=other_vet_user, crmv="67890")
    vet.clinicas.append(clinic)
    other_vet.clinicas.append(clinic)

    tutor_one = _create_tutor("Tutor One", "tutor1@example.com", clinic)
    tutor_two = _create_tutor("Tutor Two", "tutor2@example.com", clinic)

    animal_one = Animal(name="Paciente A", owner=tutor_one, clinica=clinic)
    animal_two = Animal(name="Paciente B", owner=tutor_two, clinica=clinic)
    animal_extra = Animal(name="Paciente Livre", owner=tutor_one, clinica=clinic)

    appointment_one = Appointment(
        animal=animal_one,
        tutor=tutor_one,
        veterinario=vet,
        clinica=clinic,
        scheduled_at=now,
        status="scheduled",
    )
    appointment_other = Appointment(
        animal=animal_two,
        tutor=tutor_two,
        veterinario=other_vet,
        clinica=clinic,
        scheduled_at=now + timedelta(hours=1),
        status="scheduled",
    )

    db.session.add_all(
        [
            clinic,
            vet_user,
            other_vet_user,
            vet,
            other_vet,
            tutor_one,
            tutor_two,
            animal_one,
            animal_two,
            animal_extra,
            appointment_one,
            appointment_other,
        ]
    )
    db.session.commit()

    with flask_app.test_request_context():
        animais, _, _ = _get_recent_animais(
            "all",
            1,
            clinic_id=clinic.id,
            require_appointments=True,
            veterinario_id=vet.id,
        )
        assert [animal.id for animal in animais] == [animal_one.id]

        tutores, _, _ = _get_recent_tutores(
            "all",
            1,
            clinic_id=clinic.id,
            require_appointments=True,
            veterinario_id=vet.id,
        )
        assert [tutor.id for tutor in tutores] == [tutor_one.id]
