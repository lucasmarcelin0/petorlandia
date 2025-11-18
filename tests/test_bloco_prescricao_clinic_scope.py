import os
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')

from app import app as flask_app, db
from models import Animal, BlocoPrescricao, Clinica, Consulta, User, Veterinario


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    yield flask_app


def test_bloco_prescricao_uses_animal_clinic_when_consulta_missing(app):
    with app.app_context():
        db.drop_all()
        db.create_all()

        clinic = Clinica(nome='Clinica Fallback')
        db.session.add(clinic)
        db.session.flush()

        vet_user = User(name='Vet', email='vet@example.com', worker='veterinario', role='veterinario')
        vet_user.set_password('secret')
        vet = Veterinario(user=vet_user, crmv='12345', clinica=clinic)

        tutor = User(name='Tutor', email='tutor@example.com')
        tutor.set_password('secret')
        animal = Animal(name='Bidu', owner=tutor, clinica=clinic)

        db.session.add_all([vet_user, vet, tutor, animal])
        db.session.flush()

        consulta = Consulta(animal=animal, created_by=vet_user.id, status='in_progress')

        db.session.add(consulta)
        db.session.commit()
        consulta_id = consulta.id
        clinic_id = clinic.id

    client = app.test_client()
    with client:
        login_resp = client.post(
            '/login', data={'email': 'vet@example.com', 'password': 'secret'}, follow_redirects=True
        )
        assert login_resp.status_code == 200

        resp = client.post(
            f'/consulta/{consulta_id}/bloco_prescricao',
            json={'prescricoes': [{'medicamento': 'Antibiótico'}]},
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['success'] is True

    with app.app_context():
        bloco = BlocoPrescricao.query.one()
        consulta = Consulta.query.get(consulta_id)
        assert bloco.clinica_id == clinic_id
        assert consulta.clinica_id == clinic_id
        db.drop_all()
