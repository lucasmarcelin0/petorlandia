import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db
from models import User, Clinica, Veterinario, Animal, Consulta
from sqlalchemy import or_
from flask_login import current_user

@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    with flask_app.app_context():
        db.create_all()
    yield flask_app


def login(monkeypatch, user):
    import flask_login.utils as login_utils
    from flask_login import login_user
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)
    with flask_app.test_request_context():
        login_user(user)


def test_users_share_clinic_data(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinic = Clinica(nome="Clinic")
        other_clinic = Clinica(nome="Other Clinic")
        vet_user = User(name="Vet", email="vet@example.com", password_hash="x", worker="veterinario")
        vet = Veterinario(user=vet_user, crmv="123", clinica=clinic)
        colab_user = User(
            name="Colab",
            email="colab@example.com",
            password_hash="y",
            worker="colaborador",
            clinica=clinic,
        )
        other_tutor = User(
            name="Other Clinic Tutor",
            email="other-clinic-tutor@example.com",
            password_hash="z",
            clinica=other_clinic,
        )
        other_animal = Animal(
            name="Other Clinic Animal",
            owner=other_tutor,
            clinica=other_clinic,
        )
        db.session.add_all([
            clinic,
            other_clinic,
            vet_user,
            vet,
            colab_user,
            other_tutor,
            other_animal,
        ])
        db.session.commit()

        # veterinarian adds tutor and animal
        login(monkeypatch, vet_user)
        client.post('/tutores', data={
            'name': 'Same Clinic Tutor', 'email': 't@t.com',
            # Endereço passou a ser obrigatório no cadastro de tutores.
            'rua': 'Rua A', 'cidade': 'Orlandia', 'estado': 'SP',
        })
        tutor = User.query.filter_by(email='t@t.com').first()
        assert tutor.clinica_id == clinic.id

        client.post('/novo_animal', data={
            'tutor_id': tutor.id,
            'name': 'Same Clinic Animal',
            'sex': 'M',
        })
        animal = Animal.query.filter_by(name='Same Clinic Animal').first()
        assert animal.clinica_id == clinic.id

        vet_tutors = client.get('/tutores?scope=all')
        assert b'Same Clinic Tutor' in vet_tutors.data
        assert b'Other Clinic Tutor' not in vet_tutors.data

        vet_animals = client.get('/novo_animal?scope=all')
        assert b'Same Clinic Animal' in vet_animals.data
        assert b'Other Clinic Animal' not in vet_animals.data

        client.get('/logout')
        login(monkeypatch, colab_user)

        with app.test_request_context():
            # query using same filters as the view
            tutores_mine = (
                User.query.filter(User.created_at != None, User.clinica_id == clinic.id)
                .filter(
                    or_(
                        User.added_by_id == current_user.id,
                        db.session.query(Consulta.id)
                        .join(Animal, Consulta.animal_id == Animal.id)
                        .filter(
                            Consulta.created_by == current_user.id,
                            Animal.user_id == User.id,
                        )
                        .exists(),
                    )
                )
                .all()
            )
            assert tutor not in tutores_mine

            animais_mine = (
                Animal.query.filter(Animal.removido_em == None, Animal.clinica_id == clinic.id)
                .filter(
                    or_(
                        Animal.added_by_id == current_user.id,
                        db.session.query(Consulta.id)
                        .filter(
                            Consulta.animal_id == Animal.id,
                            Consulta.created_by == current_user.id,
                        )
                        .exists(),
                    )
                )
                .all()
            )
            assert animal not in animais_mine

        resp_all = client.get('/tutores?scope=all')
        assert resp_all.status_code == 200
        assert b'Same Clinic Tutor' in resp_all.data
        assert b'Other Clinic Tutor' not in resp_all.data

        resp_animals_all = client.get('/novo_animal?scope=all')
        assert resp_animals_all.status_code == 200
        assert b'Same Clinic Animal' in resp_animals_all.data
        assert b'Other Clinic Animal' not in resp_animals_all.data

        db.session.remove()
        db.drop_all()
