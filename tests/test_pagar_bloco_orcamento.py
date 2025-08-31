import os, sys
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import app as app_module
from app import app as flask_app, db
from models import User, Animal, Consulta, OrcamentoItem, BlocoOrcamento, Clinica, Veterinario


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_pagar_bloco_orcamento(app, monkeypatch):
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
        item = OrcamentoItem(consulta=consulta, descricao='Consulta', valor=50)
        db.session.add_all([consulta, item])
        db.session.commit()
        consulta_id = consulta.id

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'vet@example.com', 'password': 'x'}, follow_redirects=True)
        resp = client.post(f'/consulta/{consulta_id}/bloco_orcamento', headers={'Accept': 'application/json'})
        assert resp.status_code == 200
        with app.app_context():
            bloco = BlocoOrcamento.query.first()
            bloco_id = bloco.id

        class FakePrefService:
            def create(self, data):
                return {'status': 201, 'response': {'init_point': 'http://mp'}}

        class FakeSDK:
            def preference(self):
                return FakePrefService()

        monkeypatch.setattr(app_module, 'mp_sdk', lambda: FakeSDK())
        resp = client.get(f'/pagar_bloco_orcamento/{bloco_id}')
        assert resp.status_code == 302
        assert resp.headers['Location'] == 'http://mp'

    with app.app_context():
        db.drop_all()
