import os
import sys
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Animal, Consulta, OrcamentoItem


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_dashboard_orcamentos(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        vet = User(name='Vet', email='vet@example.com', worker='veterinario', role='admin')
        vet.set_password('x')
        tutor = User(name='Tutor', email='tutor@example.com')
        tutor.set_password('y')
        animal = Animal(name='Rex', owner=tutor)
        db.session.add_all([vet, tutor, animal])
        db.session.commit()
        consulta = Consulta(animal_id=animal.id, created_by=vet.id, status='in_progress')
        db.session.add(consulta)
        db.session.commit()
        item = OrcamentoItem(consulta=consulta, descricao='Consulta', valor=50)
        db.session.add(item)
        db.session.commit()

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.get('/dashboard/orcamentos')
        assert resp.status_code == 200
        assert b'Tutor' in resp.data
        assert b'Rex' in resp.data
        assert b'50.00' in resp.data

    with app.app_context():
        db.drop_all()
