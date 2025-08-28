import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Clinica, Animal, ClinicAnimalAccess


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_clinic_employee_visibility(app):
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="C1")
        c2 = Clinica(nome="C2")
        tutor = User(name="Tutor", email="t@x", password_hash="x")
        emp1 = User(name="E1", email="e1@x", password_hash="x", clinica=c1)
        emp2 = User(name="E2", email="e2@x", password_hash="x", clinica=c2)
        db.session.add_all([c1, c2, tutor, emp1, emp2])
        db.session.commit()

        a1 = Animal(name="A1", owner=tutor, clinica=c1)
        a2 = Animal(name="A2", owner=tutor, clinica=c2)
        a3 = Animal(name="A3", owner=tutor)
        db.session.add_all([a1, a2, a3])
        db.session.commit()

        share = ClinicAnimalAccess(animal=a3, clinic=c1)
        db.session.add(share)
        db.session.commit()

        names1 = {a.name for a in Animal.visible_to(emp1).all()}
        names2 = {a.name for a in Animal.visible_to(emp2).all()}

        assert names1 == {"A1", "A3"}
        assert names2 == {"A2"}
