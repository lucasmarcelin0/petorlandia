import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import (
    User,
    Clinica,
    Veterinario,
    Animal,
    Consulta,
    BlocoOrcamento,
    OrcamentoItem,
    BlocoPrescricao,
    Prescricao,
)


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def login(monkeypatch, user):
    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def test_user_cannot_access_other_clinic(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        user = User(name="User", email="user@example.com", password_hash="x")
        vet = Veterinario(user=user, crmv="123", clinica=c1)
        db.session.add_all([c1, c2, user, vet])
        db.session.commit()
        login(monkeypatch, user)
        resp = client.get(f"/clinica/{c2.id}")
        assert resp.status_code == 404


def test_user_sees_own_clinic(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        user = User(name="User", email="user3@example.com", password_hash="x")
        vet = Veterinario(user=user, crmv="123", clinica=c1)
        db.session.add_all([c1, user, vet])
        db.session.commit()
        login(monkeypatch, user)
        resp = client.get(f"/clinica/{c1.id}")
        assert resp.status_code == 200
        assert b"Clinic One" in resp.data


def test_admin_can_access_any_clinic(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        admin = User(name="Admin", email="admin@example.com", password_hash="x", role="admin")
        db.session.add_all([c1, c2, admin])
        db.session.commit()
        login(monkeypatch, admin)
        resp = client.get(f"/clinica/{c2.id}")
        assert resp.status_code == 200


def test_vet_can_access_other_clinic_consulta(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        tutor = User(name="Tutor", email="tutor@example.com", password_hash="x", clinica=c1)
        animal = Animal(name="Rex", owner=tutor)
        user = User(name="User", email="user2@example.com", password_hash="x", worker="veterinario")
        vet = Veterinario(user=user, crmv="123", clinica=c1)
        other_user = User(name="OtherVet", email="other@example.com", password_hash="z", worker="veterinario")
        vet2 = Veterinario(user=other_user, crmv="999", clinica=c2)
        db.session.add_all([c1, c2, tutor, animal, user, vet, other_user, vet2])
        db.session.commit()
        consulta_c2 = Consulta(animal_id=animal.id, created_by=other_user.id, clinica_id=c2.id,
                               queixa_principal="dados c2", status='in_progress')
        db.session.add(consulta_c2)
        db.session.commit()
        login(monkeypatch, user)
        resp = client.get(f"/consulta/{animal.id}")
        assert resp.status_code == 200
        consulta_c1 = Consulta.query.filter_by(animal_id=animal.id, clinica_id=c1.id).first()
        assert consulta_c1 is not None
        assert consulta_c1.id != consulta_c2.id
        assert consulta_c1.queixa_principal is None


def test_colaborador_can_access_other_clinic_consulta(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        tutor = User(name="Tutor", email="tutor3@example.com", password_hash="x", clinica=c1)
        animal = Animal(name="Rex", owner=tutor)
        colaborador = User(name="Colab", email="colab@example.com", password_hash="x",
                           worker="colaborador", clinica=c1)
        db.session.add_all([c1, c2, tutor, animal, colaborador])
        db.session.commit()
        login(monkeypatch, colaborador)
        resp = client.get(f"/consulta/{animal.id}")
        assert resp.status_code == 200


def test_admin_can_access_any_consulta(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        admin = User(name="Admin", email="admin2@example.com", password_hash="x", role="admin", worker="veterinario")
        tutor = User(name="Tutor", email="tutor2@example.com", password_hash="y")
        animal = Animal(name="Rex", owner=tutor, clinica=c2)
        vet_admin = Veterinario(user=admin, crmv="999", clinica=c1)
        db.session.add_all([c1, c2, admin, tutor, animal, vet_admin])
        db.session.commit()
        login(monkeypatch, admin)
        resp = client.get(f"/consulta/{animal.id}")
        assert resp.status_code == 200


def test_orcamento_history_is_isolated(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        tutor = User(name="Tutor", email="t4@example.com", password_hash="x", clinica=c1)
        animal = Animal(name="Rex", owner=tutor, clinica=c1)
        vet1_user = User(name="Vet1", email="v1@example.com", password_hash="x", worker="veterinario")
        vet2_user = User(name="Vet2", email="v2@example.com", password_hash="y", worker="veterinario")
        vet1 = Veterinario(user=vet1_user, crmv="111", clinica=c1)
        vet2 = Veterinario(user=vet2_user, crmv="222", clinica=c2)
        tutor.added_by_id = vet2_user.id
        db.session.add_all([c1, c2, tutor, animal, vet1_user, vet2_user, vet1, vet2])
        db.session.commit()
        consulta = Consulta(animal_id=animal.id, created_by=vet1_user.id, clinica_id=c1.id, status='in_progress')
        db.session.add(consulta)
        db.session.commit()
        consulta_id = consulta.id
        animal_id = animal.id
        vet1_id = vet1_user.id
        vet2_id = vet2_user.id
        clinic_id = c1.id

    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(vet1_id))
    resp = client.post(
        f"/consulta/{consulta_id}/orcamento_item",
        json={"descricao": "Consulta", "valor": 50, "clinica_id": clinic_id},
    )
    assert resp.status_code == 201
    resp = client.post(
        f"/consulta/{consulta_id}/bloco_orcamento",
        headers={"Accept": "application/json"},
        json={"clinica_id": clinic_id},
    )
    assert resp.status_code == 200

    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(vet2_id))
    resp = client.get(f"/consulta/{animal_id}")
    assert resp.status_code == 404


def test_shared_animal_history_and_prescriptions_are_scoped(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        tutor = User(name="Tutor", email="shared@example.com", password_hash="x", clinica=c1)
        animal = Animal(name="Rex", owner=tutor, clinica=c1)
        vet1_user = User(name="Vet1", email="vet1@example.com", password_hash="x", worker='veterinario')
        vet2_user = User(name="Vet2", email="vet2@example.com", password_hash="y", worker='veterinario')
        vet1 = Veterinario(user=vet1_user, crmv="111", clinica=c1)
        vet2 = Veterinario(user=vet2_user, crmv="222", clinica=c2)
        tutor.added_by_id = vet2_user.id
        db.session.add_all([c1, c2, tutor, animal, vet1_user, vet2_user, vet1, vet2])
        db.session.flush()

        consulta_c1 = Consulta(
            animal_id=animal.id,
            created_by=vet1_user.id,
            clinica_id=c1.id,
            status='finalizada',
            queixa_principal='tosse clinic one',
        )
        bloco_orc = BlocoOrcamento(animal=animal, clinica=c1)
        bloco_presc = BlocoPrescricao(animal=animal, clinica=c1, saved_by=vet1_user)
        prescricao = Prescricao(animal=animal, bloco=bloco_presc, medicamento='Antibiotico C1')
        item = OrcamentoItem(bloco=bloco_orc, descricao='Exame sangue', valor=50, clinica=c1)
        db.session.add_all([consulta_c1, bloco_orc, bloco_presc, prescricao, item])
        db.session.commit()
        animal_id = animal.id
        vet1_id = vet1_user.id
        vet2_id = vet2_user.id

    import flask_login.utils as login_utils

    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(vet1_id))
    resp = client.get(f"/consulta/{animal_id}")
    assert resp.status_code == 200
    assert b"tosse clinic one" in resp.data
    assert b"R$ 50.00" in resp.data
    assert b"Antibiotico C1" in resp.data

    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(vet2_id))
    resp = client.get(f"/consulta/{animal_id}")
    assert resp.status_code == 404
