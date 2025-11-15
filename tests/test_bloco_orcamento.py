import os
import json
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Animal, Consulta, OrcamentoItem, BlocoOrcamento, Clinica, Veterinario


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_salvar_bloco_orcamento(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinica = Clinica(nome='Clinica 1')
        vet = User(name='Vet', email='vet@example.com', worker='veterinario', role='admin')
        vet.set_password('x')
        vet_v = Veterinario(user=vet, crmv='123', clinica=clinica)
        tutor = User(name='Tutor', email='tutor@example.com')
        tutor.set_password('y')
        animal = Animal(name='Rex', owner=tutor, clinica=clinica)
        db.session.add_all([clinica, vet, vet_v, tutor, animal])
        db.session.commit()
        consulta = Consulta(animal=animal, created_by=vet.id, status='in_progress', clinica_id=clinica.id)
        item1 = OrcamentoItem(consulta=consulta, descricao='Consulta', valor=50, clinica=clinica)
        item2 = OrcamentoItem(consulta=consulta, descricao='Exame', valor=30, clinica=clinica)
        db.session.add_all([consulta, item1, item2])
        db.session.commit()
        consulta_id = consulta.id
    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        payload = {
            'discount_percent': 10,
            'tutor_notes': 'Observação importante'
        }
        resp = client.post(
            f'/consulta/{consulta_id}/bloco_orcamento',
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            data=json.dumps(payload)
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success']
    with app.app_context():
        bloco = BlocoOrcamento.query.first()
        assert bloco is not None
        assert len(bloco.itens) == 2
        assert float(bloco.discount_value) > 0
        assert bloco.tutor_notes == 'Observação importante'
        consulta = Consulta.query.get(consulta_id)
        assert len(consulta.orcamento_items) == 0
        db.drop_all()
