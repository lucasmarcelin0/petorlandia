import os

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

import flask_login.utils as login_utils

from extensions import db
from models import Animal, CasaDeRacao, Racao, TipoRacao, User


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def _create_owner_and_store(name="Lojista", email="lojista-crm@example.com"):
    owner = User(name=name, email=email)
    owner.set_password("x")
    db.session.add(owner)
    db.session.flush()
    casa = CasaDeRacao(nome=f"{name} Racoes", owner_id=owner.id, status="ativa")
    db.session.add(casa)
    db.session.commit()
    return owner, casa


def test_feed_store_owner_can_create_tutor_and_animal(app, client, monkeypatch):
    with app.app_context():
        owner, casa = _create_owner_and_store()
        _login(monkeypatch, owner)

        tutor_resp = client.post(
            f"/casa-de-racao/{casa.id}/tutores",
            data={
                "name": "Maria Tutora",
                "email": "maria.tutora@example.com",
                "phone": "(11) 99999-0000",
            },
        )
        assert tutor_resp.status_code == 302

        tutor = User.query.filter_by(email="maria.tutora@example.com").one()
        assert tutor.casa_de_racao_id == casa.id
        assert tutor.clinica_id is None

        animal_resp = client.post(
            f"/casa-de-racao/{casa.id}/animais",
            data={
                "tutor_id": str(tutor.id),
                "name": "Thor",
                "age": "4 anos",
                "peso": "12,5",
                "sex": "Macho",
            },
        )
        assert animal_resp.status_code == 302

        animal = Animal.query.filter_by(name="Thor").one()
        assert animal.casa_de_racao_id == casa.id
        assert animal.clinica_id is None
        assert animal.user_id == tutor.id
        assert animal.added_by_id == owner.id


def test_feed_store_tutor_form_ignores_incomplete_address(app, client, monkeypatch):
    with app.app_context():
        owner, casa = _create_owner_and_store(email="lojista-endereco@example.com")
        _login(monkeypatch, owner)

        resp = client.post(
            f"/casa-de-racao/{casa.id}/tutores",
            data={
                "_from_dashboard": "1",
                "name": "Tutor Sem Cep",
                "email": "sem-cep@example.com",
                "rua": "Rua sem CEP",
                "cidade": "Orlandia",
                "estado": "SP",
            },
            follow_redirects=False,
            headers={"Accept": "text/html"},
        )

        assert resp.status_code == 302
        tutor = User.query.filter_by(email="sem-cep@example.com").one()
        assert tutor.casa_de_racao_id == casa.id
        assert tutor.endereco_id is None


def test_feed_store_owner_can_save_pet_ration(app, client, monkeypatch):
    with app.app_context():
        owner, casa = _create_owner_and_store(email="lojista-racao@example.com")
        tutor = User(name="Tutor Racao", email="tutor-racao@example.com", casa_de_racao_id=casa.id)
        tutor.set_password("x")
        db.session.add(tutor)
        db.session.flush()
        animal = Animal(name="Nina", user_id=tutor.id, casa_de_racao_id=casa.id, status="privado")
        db.session.add(animal)
        db.session.commit()
        _login(monkeypatch, owner)

        resp = client.post(
            f"/casa-de-racao/{casa.id}/animal/{animal.id}/racoes",
            data={
                "marca": "Golden",
                "linha": "Formula Adultos",
                "preco_pago": "179,90",
                "tamanho_embalagem": "15 kg",
                "observacoes_racao": "Compra recorrente mensal.",
            },
        )

        assert resp.status_code == 302
        tipo = TipoRacao.query.filter_by(marca="Golden", linha="Formula Adultos").one()
        racao = Racao.query.filter_by(animal_id=animal.id, tipo_racao_id=tipo.id).one()
        assert racao.created_by == owner.id
        assert racao.tamanho_embalagem == "15 kg"
        assert racao.preco_pago == 179.90


def test_feed_store_crm_is_scoped_to_store_owner(app, client, monkeypatch):
    with app.app_context():
        owner, casa = _create_owner_and_store(email="lojista-um@example.com")
        other_owner = User(name="Outro Lojista", email="lojista-dois@example.com")
        other_owner.set_password("x")
        db.session.add(other_owner)
        db.session.commit()
        _login(monkeypatch, other_owner)

        resp = client.get(f"/casa-de-racao/{casa.id}/tutores", headers={"Accept": "text/html"})

        assert resp.status_code == 403


def test_feed_store_professional_pages_hide_veterinary_tabs(app, client, monkeypatch):
    with app.app_context():
        owner, casa = _create_owner_and_store(email="lojista-ui@example.com")
        _login(monkeypatch, owner)

        dashboard = client.get(f"/casa-de-racao/{casa.id}")
        assert dashboard.status_code == 200
        assert "Tutores" in dashboard.get_data(as_text=True)

        resp = client.get(f"/casa-de-racao/{casa.id}/animais")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Consulta" not in body
        assert "Exames" not in body
        assert "Medicamentos" not in body
