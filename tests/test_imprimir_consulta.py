import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

import pytest
from routes.app import app as flask_app, db
from models import User, Animal, Consulta


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_imprimir_consulta_uses_creator_data(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        vet1 = User(name='Vet1', email='vet1@example.com', worker='veterinario', role='admin')
        vet1.set_password('x')
        vet2 = User(name='Vet2', email='vet2@example.com', worker='veterinario', role='admin')
        vet2.set_password('y')
        tutor = User(name='Tutor', email='tutor@example.com')
        tutor.set_password('z')
        animal = Animal(name='Rex', owner=tutor)
        db.session.add_all([vet1, vet2, tutor, animal])
        db.session.commit()

        consulta = Consulta(animal_id=animal.id, created_by=vet1.id, status='in_progress')
        db.session.add(consulta)
        db.session.commit()
        consulta_id = consulta.id

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet2@example.com', 'password': 'y'}, follow_redirects=True)
        resp = client.get(f'/imprimir_consulta/{consulta_id}')
        assert resp.status_code == 200
        assert b'Vet1' in resp.data
        assert b'Vet2' not in resp.data

    with app.app_context():
        db.drop_all()
