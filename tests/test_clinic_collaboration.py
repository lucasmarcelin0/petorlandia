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
        db.drop_all()
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()


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
        vet_user = User(name="Vet", email="vet@example.com", password_hash="x", worker="veterinario")
        vet = Veterinario(user=vet_user, crmv="123", clinica=clinic)
        colab_user = User(name="Colab", email="colab@example.com", password_hash="y", worker="colaborador", clinica_id=clinic.id)
        db.session.add_all([clinic, vet_user, vet, colab_user])
        db.session.commit()

        # veterinarian adds tutor and animal
        login(monkeypatch, vet_user)
        client.post('/tutores', data={'name': 'Tutor', 'email': 't@t.com'})
        tutor = User.query.filter_by(email='t@t.com').first()
        assert tutor.clinica_id == clinic.id

        client.post('/novo_animal', data={'tutor_id': tutor.id, 'name': 'Rex', 'sex': 'M'})
        animal = Animal.query.filter_by(name='Rex').first()
        assert animal.clinica_id == clinic.id

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
        resp_animals_all = client.get('/novo_animal?scope=all')
        assert resp_animals_all.status_code == 200

        db.session.remove()
        db.drop_all()
