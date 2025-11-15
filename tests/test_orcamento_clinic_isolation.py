import pytest
from types import SimpleNamespace

from app import app as flask_app, db
from models import (
    Animal,
    BlocoOrcamento,
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


def login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _bootstrap_clinics(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinic_a = Clinica(nome='Clinic A')
        clinic_b = Clinica(nome='Clinic B')
        user = User(name='Owner', email='owner@test', worker='veterinario', clinica=clinic_a)
        user.set_password('secret')
        db.session.add_all([clinic_a, clinic_b, user])
        db.session.commit()
        return SimpleNamespace(
            user_id=user.id,
            clinic_a_id=clinic_a.id,
            clinic_b_id=clinic_b.id,
        )


def _bootstrap_consulta(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        clinic_a = Clinica(nome='Clinic A')
        clinic_b = Clinica(nome='Clinic B')
        tutor = User(name='Tutor', email='tutor@test')
        tutor.set_password('secret')
        vet_user = User(name='Vet', email='vet@test', worker='veterinario', clinica=clinic_a)
        vet_user.set_password('secret')
        db.session.add_all([clinic_a, clinic_b, tutor, vet_user])
        db.session.flush()
        vet_profile = Veterinario(user=vet_user, crmv='CRMV123', clinica=clinic_a)
        animal = Animal(name='Rex', owner=tutor, clinica=clinic_a)
        consulta = Consulta(
            animal=animal,
            created_by=vet_user.id,
            clinica_id=clinic_a.id,
            status='in_progress',
        )
        bloco = BlocoOrcamento(animal=animal, clinica=clinic_a, payment_status='draft')
        bloco.itens.append(OrcamentoItem(descricao='Exame', valor=50, clinica=clinic_a))
        db.session.add_all([vet_profile, animal, consulta, bloco])
        db.session.commit()
        return SimpleNamespace(
            vet_id=vet_user.id,
            consulta_id=consulta.id,
            bloco_id=bloco.id,
            clinic_a_id=clinic_a.id,
            clinic_b_id=clinic_b.id,
        )


def test_novo_orcamento_requires_matching_clinic_id(app):
    data = _bootstrap_clinics(app)
    client = app.test_client()
    login(client, data.user_id)

    resp = client.post(
        f'/clinica/{data.clinic_a_id}/novo_orcamento',
        data={'descricao': 'Consulta inicial', 'clinica_id': str(data.clinic_a_id)},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    resp = client.post(
        f'/clinica/{data.clinic_a_id}/novo_orcamento',
        data={'descricao': 'Acesso inválido', 'clinica_id': str(data.clinic_b_id)},
        follow_redirects=False,
    )
    assert resp.status_code == 404

    with app.app_context():
        assert Orcamento.query.filter_by(descricao='Consulta inicial').count() == 1
        assert Orcamento.query.filter_by(descricao='Acesso inválido').count() == 0


def test_adicionar_orcamento_item_enforces_clinic_scope(app):
    data = _bootstrap_consulta(app)
    client = app.test_client()
    login(client, data.vet_id)

    payload = {'descricao': 'Vacina', 'valor': 120, 'payer_type': 'particular'}

    resp = client.post(
        f'/consulta/{data.consulta_id}/orcamento_item',
        json=payload,
    )
    assert resp.status_code == 400

    payload['clinica_id'] = data.clinic_a_id
    resp = client.post(
        f'/consulta/{data.consulta_id}/orcamento_item',
        json=payload,
    )
    assert resp.status_code == 201

    resp = client.post(
        f'/consulta/{data.consulta_id}/orcamento_item',
        json={**payload, 'clinica_id': data.clinic_b_id},
    )
    assert resp.status_code == 404


def test_atualizar_bloco_orcamento_blocks_cross_clinic_edits(app):
    data = _bootstrap_consulta(app)
    client = app.test_client()
    login(client, data.vet_id)
    body = {
        'itens': [{'descricao': 'Revisão', 'valor': 80}],
        'clinica_id': data.clinic_b_id,
    }
    resp = client.post(
        f'/bloco_orcamento/{data.bloco_id}/atualizar',
        json=body,
        headers={'Accept': 'application/json'},
    )
    assert resp.status_code == 404

    body['clinica_id'] = data.clinic_a_id
    resp = client.post(
        f'/bloco_orcamento/{data.bloco_id}/atualizar',
        json=body,
        headers={'Accept': 'application/json'},
    )
    assert resp.status_code == 200
