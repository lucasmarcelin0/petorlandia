import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from routes.app import app as flask_app, db
from models import User, Animal, Clinica, Veterinario, OrcamentoItem, BlocoOrcamento


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_editar_bloco_orcamento(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinica = Clinica(nome='Clinica 1')
        vet_user = User(name='Vet', email='vet@example.com', worker='veterinario', role='admin')
        vet_user.set_password('x')
        vet = Veterinario(user=vet_user, crmv='123', clinica=clinica)
        tutor = User(name='Tutor', email='tutor@example.com')
        tutor.set_password('y')
        animal = Animal(name='Rex', owner=tutor, clinica=clinica)
        bloco = BlocoOrcamento(animal=animal, clinica=clinica)
        item = OrcamentoItem(bloco=bloco, descricao='Consulta', valor=50)
        db.session.add_all([clinica, vet_user, vet, tutor, animal, bloco, item])
        db.session.commit()
        bloco_id = bloco.id
    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.post(
            f'/bloco_orcamento/{bloco_id}/atualizar',
            json={'itens': [{'descricao': 'Procedimento', 'valor': 100}]},
            headers={'Accept': 'application/json'}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success']
    with app.app_context():
        bloco = BlocoOrcamento.query.get(bloco_id)
        assert len(bloco.itens) == 1
        assert bloco.itens[0].descricao == 'Procedimento'
        assert float(bloco.itens[0].valor) == 100.0
        db.drop_all()
