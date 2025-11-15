import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from datetime import datetime
from app import app as flask_app, db
from models import User, Clinica, Veterinario, Animal, Consulta, TutorClinicShare


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
        tutor = User(name="Tutor", email="tutor@example.com", password_hash="x")
        animal = Animal(name="Rex", owner=tutor, clinica=c2)
        user = User(name="User", email="user2@example.com", password_hash="x", worker="veterinario")
        vet = Veterinario(user=user, crmv="123", clinica=c1)
        other_user = User(name="OtherVet", email="other@example.com", password_hash="z", worker="veterinario")
        vet2 = Veterinario(user=other_user, crmv="999", clinica=c2)
        db.session.add_all([c1, c2, tutor, animal, user, vet, other_user, vet2])
        db.session.commit()
        share = TutorClinicShare(tutor_id=tutor.id, clinica_id=c1.id, granted_by_id=user.id)
        db.session.add(share)
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
        tutor = User(name="Tutor", email="tutor3@example.com", password_hash="x")
        animal = Animal(name="Rex", owner=tutor, clinica=c2)
        colaborador = User(name="Colab", email="colab@example.com", password_hash="x",
                           worker="colaborador", clinica=c1)
        db.session.add_all([c1, c2, tutor, animal, colaborador])
        db.session.commit()
        share = TutorClinicShare(tutor_id=tutor.id, clinica_id=c1.id, granted_by_id=colaborador.id)
        db.session.add(share)
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
        tutor = User(name="Tutor", email="t4@example.com", password_hash="x")
        animal = Animal(name="Rex", owner=tutor, clinica=c1)
        vet1_user = User(name="Vet1", email="v1@example.com", password_hash="x", worker="veterinario")
        vet2_user = User(name="Vet2", email="v2@example.com", password_hash="y", worker="veterinario")
        vet1 = Veterinario(user=vet1_user, crmv="111", clinica=c1)
        vet2 = Veterinario(user=vet2_user, crmv="222", clinica=c2)
        db.session.add_all([c1, c2, tutor, animal, vet1_user, vet2_user, vet1, vet2])
        db.session.commit()
        share = TutorClinicShare(tutor_id=tutor.id, clinica_id=c2.id, granted_by_id=vet1_user.id)
        db.session.add(share)
        db.session.commit()
        consulta = Consulta(animal_id=animal.id, created_by=vet1_user.id, clinica_id=c1.id, status='in_progress')
        db.session.add(consulta)
        db.session.commit()
        consulta_id = consulta.id
        animal_id = animal.id
        vet1_id = vet1_user.id
        vet2_id = vet2_user.id

    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(vet1_id))
    resp = client.post(
        f"/consulta/{consulta_id}/orcamento_item",
        json={"descricao": "Consulta", "valor": 50},
    )
    assert resp.status_code == 201
    resp = client.post(
        f"/consulta/{consulta_id}/bloco_orcamento",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 200

    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(vet2_id))
    resp = client.get(f"/consulta/{animal_id}")
    assert resp.status_code == 200
    assert b"Nenhum or\xc3\xa7amento registrado ainda." in resp.data
    assert b"R$ 50.00" not in resp.data


def test_tutor_access_denied_without_share(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinic_a = Clinica(nome="Clinic A")
        clinic_b = Clinica(nome="Clinic B")
        tutor = User(name="Tutor", email="tutor_share@example.com", password_hash="x", clinica=clinic_a)
        vet_user = User(name="OtherVet", email="vetb@example.com", password_hash="x", worker="veterinario")
        vet = Veterinario(user=vet_user, crmv="12345", clinica=clinic_b)
        db.session.add_all([clinic_a, clinic_b, tutor, vet_user, vet])
        db.session.commit()
        login(monkeypatch, vet_user)
        resp = client.get(f"/tutor/{tutor.id}")
        assert resp.status_code == 404


def test_tutor_share_grants_and_revokes_access(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinic_a = Clinica(nome="Clinic A")
        clinic_b = Clinica(nome="Clinic B")
        tutor = User(name="Tutor", email="tutor_share2@example.com", password_hash="x", clinica=clinic_a)
        animal = Animal(name="Rex", owner=tutor, clinica=clinic_a)
        vet_user = User(name="SharedVet", email="vetshare@example.com", password_hash="x", worker="veterinario")
        vet = Veterinario(user=vet_user, crmv="999", clinica=clinic_b)
        db.session.add_all([clinic_a, clinic_b, tutor, animal, vet_user, vet])
        db.session.commit()

        share = TutorClinicShare(tutor_id=tutor.id, clinica_id=clinic_b.id, granted_by_id=vet_user.id)
        db.session.add(share)
        db.session.commit()

        login(monkeypatch, vet_user)
        resp = client.get(f"/consulta/{animal.id}")
        assert resp.status_code == 200
        resp_tutor = client.get(f"/tutor/{tutor.id}")
        assert resp_tutor.status_code == 200

        share.revoked_at = datetime.utcnow()
        db.session.commit()

        resp_after = client.get(f"/consulta/{animal.id}")
        assert resp_after.status_code == 404
        resp_tutor_after = client.get(f"/tutor/{tutor.id}")
        assert resp_tutor_after.status_code == 404
