import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from extensions import db
from models import Animal, User


def test_user_name_is_normalized_before_save(app):
    with app.app_context():
        user = User(
            name="  mArIa   dA   siLvA  ",
            email="maria-normalizada@test.com",
            password_hash="x",
        )
        db.session.add(user)
        db.session.commit()

        assert user.name == "Maria Da Silva"


def test_animal_name_is_normalized_before_save(app):
    with app.app_context():
        tutor = User(
            name="joAO souza",
            email="tutor-animal-normalizado@test.com",
            password_hash="x",
        )
        db.session.add(tutor)
        db.session.commit()

        animal = Animal(name="  bELinha  do   sOl  ", user_id=tutor.id)
        db.session.add(animal)
        db.session.commit()

        assert animal.name == "Belinha Do Sol"
