import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import time

import pytest
from app import app as flask_app, db
from models import User, Clinica, ClinicStaff, ClinicHours


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_delete_clinic_removes_hours_and_staff(app):
    with app.app_context():
        db.drop_all()
        db.create_all()

        owner = User(name="Owner", email="owner@example.com", password_hash="x")
        staff_user = User(name="Staff", email="staff@example.com", password_hash="x")
        clinic = Clinica(nome="Clinica X", owner=owner)
        db.session.add_all([owner, staff_user, clinic])
        db.session.commit()

        hour = ClinicHours(
            clinica_id=clinic.id,
            dia_semana="Segunda",
            hora_abertura=time(8, 0),
            hora_fechamento=time(18, 0),
        )
        staff = ClinicStaff(clinic_id=clinic.id, user_id=staff_user.id)
        db.session.add_all([hour, staff])
        db.session.commit()

        db.session.delete(clinic)
        db.session.commit()

        assert Clinica.query.get(clinic.id) is None
        assert ClinicHours.query.filter_by(clinica_id=clinic.id).count() == 0
        assert ClinicStaff.query.filter_by(clinic_id=clinic.id).count() == 0
