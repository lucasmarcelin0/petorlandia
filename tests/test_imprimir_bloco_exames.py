import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime

import pytest
from app import app as flask_app, db
from models import User, Animal, Clinica, BlocoExames, ExameSolicitado


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_imprimir_bloco_exames_requer_clinica(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        tutor = User(name="Tutor", email="tutor@example.com")
        tutor.set_password('x')
        animal = Animal(name="Rex", owner=tutor)
        bloco = BlocoExames(animal=animal)
        exame = ExameSolicitado(
            bloco=bloco,
            nome="Ultrassonografia abdominal",
            status="concluido",
            resultado="Cistite e hiperplasia prostatica.",
            performed_at=datetime(2026, 2, 16),
            laudo_filename="Ultrassom SID,Rosa.pdf",
        )
        clinica = Clinica(nome="Pet Clinic")
        db.session.add_all([tutor, animal, bloco, exame, clinica])
        db.session.commit()
        bloco_id = bloco.id
        clinica_id = clinica.id

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'tutor@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.get(f'/imprimir_bloco_exames/{bloco_id}')
        assert resp.status_code == 400
        resp = client.get(f'/imprimir_bloco_exames/{bloco_id}?clinica_id={clinica_id}')
        assert resp.status_code == 200
        assert b'Pet Clinic' in resp.data
        assert b'Ultrassonografia abdominal' in resp.data
        assert b'Cistite e hiperplasia prostatica.' in resp.data
        assert b'Ultrassom SID,Rosa.pdf' in resp.data

    with app.app_context():
        db.drop_all()
