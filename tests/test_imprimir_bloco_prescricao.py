import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

from app import app as flask_app, db
from models import Animal, BlocoPrescricao, Consulta, User, Veterinario


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    yield flask_app


def _create_veterinarian(name: str, email: str, password: str, crmv: str) -> User:
    vet = User(name=name, email=email, worker='veterinario', role='admin')
    vet.set_password(password)
    db.session.add(vet)
    db.session.flush()
    db.session.add(Veterinario(user=vet, crmv=crmv))
    return vet


def test_imprimir_bloco_prescricao_displays_printing_user(app):
    with app.app_context():
        db.drop_all()
        db.create_all()

        vet1 = _create_veterinarian('Vet1', 'vet1@example.com', 'pw1', 'SP-123')
        vet2 = _create_veterinarian('Vet2', 'vet2@example.com', 'pw2', 'SP-456')

        tutor = User(name='Tutor', email='tutor@example.com')
        tutor.set_password('pw3')
        animal = Animal(name='Jurema', owner=tutor)

        db.session.add_all([tutor, animal])
        db.session.flush()

        consulta = Consulta(animal_id=animal.id, created_by=vet1.id, status='in_progress')
        bloco = BlocoPrescricao(animal=animal, saved_by=vet1)
        db.session.add_all([consulta, bloco])
        db.session.commit()
        bloco_id = bloco.id

    client = app.test_client()
    with client:
        login_resp = client.post(
            '/login',
            data={'email': 'vet2@example.com', 'password': 'pw2'},
            follow_redirects=True,
        )
        assert login_resp.status_code == 200

        resp = client.get(f'/bloco_prescricao/{bloco_id}/imprimir')
        assert resp.status_code == 200

        html = resp.get_data(as_text=True)
        assert 'Impresso por:' in html
        assert 'Vet2' in html
        assert 'CRMV SP-456' in html

    with app.app_context():
        db.drop_all()
