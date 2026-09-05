import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app as flask_app, db
from models import User, Clinica, Veterinario, Animal, Consulta


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    with flask_app.app_context():
        db.create_all()
    yield flask_app


def login(monkeypatch, user):
    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def test_tutor_sees_consultas_from_all_clinics(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        c1 = Clinica(nome="Clinic One")
        c2 = Clinica(nome="Clinic Two")
        tutor = User(name="Tutor", email="tutor@example.com", password_hash="x")
        animal = Animal(name="Rex", owner=tutor, clinica=c1)
        vet1_user = User(name="VetOne", email="v1@example.com", password_hash="x", worker="veterinario")
        vet1 = Veterinario(user=vet1_user, crmv="111", clinica=c1)
        vet2_user = User(name="VetTwo", email="v2@example.com", password_hash="x", worker="veterinario")
        vet2 = Veterinario(user=vet2_user, crmv="222", clinica=c2)
        db.session.add_all([c1, c2, tutor, animal, vet1_user, vet1, vet2_user, vet2])
        db.session.commit()
        consulta1 = Consulta(animal_id=animal.id, created_by=vet1_user.id, clinica_id=c1.id, status='finalizada')
        consulta2 = Consulta(animal_id=animal.id, created_by=vet2_user.id, clinica_id=c2.id, status='finalizada')
        db.session.add_all([consulta1, consulta2])
        db.session.commit()
        login(monkeypatch, tutor)
        resp = client.get(f"/animal/{animal.id}/ficha")
        assert resp.status_code == 200

        # O histórico é carregado por AJAX; a seção devolve o HTML renderizado.
        resp = client.get(
            f"/animal/{animal.id}/ficha?section=history",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["success"] is True
        # O template aplica |title ao nome (VetOne -> Vetone).
        html_lower = payload["html"].lower()
        assert "vetone" in html_lower
        assert "vettwo" in html_lower


def test_veterinarian_and_admin_open_ficha_animal_and_render_documents(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinica = Clinica(nome="Clinic Test")
        tutor = User(name="Tutor Test", email="tutor_test@example.com", password_hash="x")
        animal = Animal(name="Bob", owner=tutor, clinica=clinica)
        vet_user = User(name="Vet User", email="vet_test@example.com", password_hash="x", worker="veterinario")
        vet = Veterinario(user=vet_user, crmv="999", clinica=clinica)
        admin_user = User(name="Admin User", email="admin_test@example.com", password_hash="x", role="admin")
        db.session.add_all([clinica, tutor, animal, vet_user, vet, admin_user])
        db.session.commit()

        # Veterinário acessa a ficha: deve renderizar documentos.html sem UndefinedError
        login(monkeypatch, vet_user)
        resp_vet = client.get(f"/animal/{animal.id}/ficha")
        assert resp_vet.status_code == 200
        assert "Documentos".encode("utf-8") in resp_vet.data
        assert "Ver termos".encode("utf-8") in resp_vet.data

        # Admin acessa a ficha: deve renderizar documentos.html sem erro
        login(monkeypatch, admin_user)
        resp_admin = client.get(f"/animal/{animal.id}/ficha")
        assert resp_admin.status_code == 200
        assert "Documentos".encode("utf-8") in resp_admin.data

