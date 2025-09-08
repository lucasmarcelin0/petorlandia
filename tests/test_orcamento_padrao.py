import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Animal, Consulta, Clinica, Veterinario, Orcamento


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_adiciona_item_padrao_no_orcamento(app):
    with app.app_context():
        db.create_all()
        vet = User(name='Vet', email='vet@x.com', worker='veterinario', role='admin')
        vet.set_password('x')
        tutor = User(name='Tutor', email='tutor@x.com')
        tutor.set_password('y')
        clinica = Clinica(nome='Clinica X', owner=vet)
        vet_v = Veterinario(user=vet, crmv='123', clinica=clinica)
        animal = Animal(name='Rex', owner=tutor)
        db.session.add_all([vet, tutor, clinica, vet_v, animal])
        db.session.commit()
        consulta = Consulta(animal_id=animal.id, created_by=vet.id, clinica_id=clinica.id, status='in_progress')
        db.session.add(consulta)
        db.session.commit()
        consulta_id = consulta.id
        clinica_id = clinica.id

    client = app.test_client()
    with client:
        client.post('/login', data={'email':'vet@x.com','password':'x'}, follow_redirects=True)
        resp = client.post('/servico', json={'descricao':'Consulta', 'valor':50})
        assert resp.status_code == 201
        servico_id = resp.get_json()['id']
        resp = client.post(f'/consulta/{consulta_id}/orcamento_item', json={'servico_id': servico_id})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['descricao'] == 'Consulta'
        assert data['valor'] == 50.0

    with app.app_context():
        orcamento = Orcamento.query.filter_by(clinica_id=clinica_id, consulta_id=consulta_id).first()
        assert orcamento is not None
        assert len(orcamento.items) == 1
        assert orcamento.items[0].descricao == 'Consulta'
