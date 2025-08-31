import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Animal, Consulta, OrcamentoItem, BlocoOrcamento


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_salvar_bloco_orcamento(app):
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
        consulta = Consulta(animal=animal, created_by=vet.id, status='in_progress')
        item1 = OrcamentoItem(consulta=consulta, descricao='Consulta', valor=50)
        item2 = OrcamentoItem(consulta=consulta, descricao='Exame', valor=30)
        db.session.add_all([consulta, item1, item2])
        db.session.commit()
        consulta_id = consulta.id
    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.post(f'/consulta/{consulta_id}/bloco_orcamento', headers={'Accept': 'application/json'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success']
    with app.app_context():
        bloco = BlocoOrcamento.query.first()
        assert bloco is not None
        assert len(bloco.itens) == 2
        consulta = Consulta.query.get(consulta_id)
        assert len(consulta.orcamento_items) == 0
        db.drop_all()
