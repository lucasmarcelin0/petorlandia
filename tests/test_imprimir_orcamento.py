import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

from app import app as flask_app, db
from models import (
    Animal,
    Clinica,
    Consulta,
    Orcamento,
    OrcamentoItem,
    User,
    Veterinario,
)


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


def _create_tutor(name: str, email: str, password: str) -> User:
    tutor = User(name=name, email=email)
    tutor.set_password(password)
    db.session.add(tutor)
    return tutor


def test_imprimir_orcamento_includes_printing_user_details(app):
    with app.app_context():
        db.drop_all()
        db.create_all()

        vet = _create_veterinarian('Vet', 'vet@example.com', 'x', 'SP-789')
        tutor = _create_tutor('Tutor', 'tutor@example.com', 'y')
        animal = Animal(name='Rex', owner=tutor)
        db.session.add(animal)
        db.session.flush()

        consulta = Consulta(animal_id=animal.id, created_by=vet.id, status='in_progress')
        db.session.add(consulta)
        db.session.flush()

        item = OrcamentoItem(consulta=consulta, descricao='Consulta', valor=50)
        db.session.add(item)
        db.session.commit()
        consulta_id = consulta.id

    client = app.test_client()
    with client:
        login_resp = client.post(
            '/login',
            data={'email': 'vet@example.com', 'password': 'x'},
            follow_redirects=True,
        )
        assert login_resp.status_code == 200

        resp = client.get(f'/imprimir_orcamento/{consulta_id}')
        assert resp.status_code == 200

        html = resp.get_data(as_text=True)
        assert 'Impresso por:' in html
        assert 'Vet' in html
        assert 'CRMV SP-789' in html
        assert 'Profissional responsável registrado' not in html

    with app.app_context():
        db.drop_all()


def test_imprimir_orcamento_displays_original_vet_when_different(app):
    with app.app_context():
        db.drop_all()
        db.create_all()

        vet1 = _create_veterinarian('Vet1', 'vet1@example.com', 'x', 'SP-101')
        vet2 = _create_veterinarian('Vet2', 'vet2@example.com', 'y', 'SP-202')
        tutor = _create_tutor('Tutor', 'tutor@example.com', 'z')
        animal = Animal(name='Rex', owner=tutor)
        db.session.add(animal)
        db.session.flush()

        consulta = Consulta(animal_id=animal.id, created_by=vet1.id, status='in_progress')
        db.session.add(consulta)
        db.session.flush()

        item = OrcamentoItem(consulta=consulta, descricao='Consulta', valor=80)
        db.session.add(item)
        db.session.commit()
        consulta_id = consulta.id

    client = app.test_client()
    with client:
        login_resp = client.post(
            '/login',
            data={'email': 'vet2@example.com', 'password': 'y'},
            follow_redirects=True,
        )
        assert login_resp.status_code == 200

        resp = client.get(f'/imprimir_orcamento/{consulta_id}')
        assert resp.status_code == 200

        html = resp.get_data(as_text=True)
        assert 'Impresso por:' in html
        assert 'Vet2' in html
        assert 'CRMV SP-202' in html
        assert 'Profissional responsável registrado: Vet1' in html

    with app.app_context():
        db.drop_all()


def test_imprimir_orcamento_padrao_includes_printing_user_details(app):
    with app.app_context():
        db.drop_all()
        db.create_all()

        vet = _create_veterinarian('Vet', 'vet@example.com', 'x', 'SP-303')
        clinica = Clinica(nome='Clinica X', owner=vet)
        db.session.add(clinica)
        db.session.flush()

        orcamento = Orcamento(clinica=clinica, descricao='Padrao')
        db.session.add(orcamento)
        db.session.flush()

        item = OrcamentoItem(orcamento=orcamento, descricao='Servico', valor=100)
        db.session.add(item)
        db.session.commit()
        orcamento_id = orcamento.id

    client = app.test_client()
    with client:
        login_resp = client.post(
            '/login',
            data={'email': 'vet@example.com', 'password': 'x'},
            follow_redirects=True,
        )
        assert login_resp.status_code == 200

        resp = client.get(f'/orcamento/{orcamento_id}/imprimir')
        assert resp.status_code == 200

        html = resp.get_data(as_text=True)
        assert 'Impresso por:' in html
        assert 'Vet' in html
        assert 'CRMV SP-303' in html

    with app.app_context():
        db.drop_all()
