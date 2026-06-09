"""Testes do módulo Petsitter, Carreiras e Indicações."""
import os
import sys
from datetime import date, timedelta

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import flask_login.utils as login_utils

from app import app as flask_app, db
from models import (
    Animal,
    CareerApplication,
    PetsitterProfile,
    PetsitterRequest,
    ReferralCode,
    ReferralSignup,
    User,
)


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def login(monkeypatch, user_id):
    def _load_user():
        return db.session.get(User, user_id)

    monkeypatch.setattr(login_utils, "_get_user", _load_user)


def _criar_tutor(name="Tutor", email="tutor@example.com", role="adotante"):
    user = User(name=name, email=email, password_hash="hash", role=role)
    db.session.add(user)
    db.session.flush()
    return user


def _criar_animal(user, nome="Rex"):
    animal = Animal(name=nome, user_id=user.id)
    db.session.add(animal)
    db.session.flush()
    return animal


# ---------------------------------------------------------------------------
# Página pública
# ---------------------------------------------------------------------------

def test_pagina_petsitter_publica(client):
    resp = client.get("/petsitter")
    assert resp.status_code == 200
    assert "Petsitter".encode() in resp.data


def test_pagina_carreiras_publica(client):
    resp = client.get("/carreiras")
    assert resp.status_code == 200
    assert "Carreiras".encode() in resp.data


# ---------------------------------------------------------------------------
# Carreiras
# ---------------------------------------------------------------------------

def test_candidatura_carreiras_cria_registro(app, client):
    resp = client.post(
        "/carreiras",
        data={
            "categoria": "especialista",
            "nome": "Dr. Ultra",
            "email": "ultra@example.com",
            "telefone": "(16) 99999-0000",
            "cidade": "Orlândia",
            "especialidade": "Ultrassonografia",
            "mensagem": "10 anos de experiência",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        candidatura = CareerApplication.query.one()
        assert candidatura.categoria == "especialista"
        assert candidatura.status == "pendente"
        assert candidatura.especialidade == "Ultrassonografia"


def test_candidatura_duplicada_nao_duplica(app, client):
    data = {
        "categoria": "petsitter",
        "nome": "Cuidadora",
        "email": "sitter@example.com",
    }
    client.post("/carreiras", data=data)
    client.post("/carreiras", data=data)
    with app.app_context():
        assert CareerApplication.query.count() == 1


def test_candidatura_categoria_invalida_nao_cria(app, client):
    client.post(
        "/carreiras",
        data={"categoria": "banda_de_rock", "nome": "X", "email": "x@example.com"},
    )
    with app.app_context():
        assert CareerApplication.query.count() == 0


# ---------------------------------------------------------------------------
# Solicitação de petsitter
# ---------------------------------------------------------------------------

def test_solicitar_petsitter_cria_solicitacao(app, client, monkeypatch):
    with app.app_context():
        tutor = _criar_tutor()
        animal = _criar_animal(tutor)
        db.session.commit()
        tutor_id, animal_id = tutor.id, animal.id

    login(monkeypatch, tutor_id)
    inicio = date.today() + timedelta(days=7)
    fim = inicio + timedelta(days=3)
    resp = client.post(
        "/petsitter/solicitar",
        data={
            "data_inicio": inicio.isoformat(),
            "data_fim": fim.isoformat(),
            "local_atendimento": "casa_sitter",
            "animal_ids": [str(animal_id)],
            "observacoes": "Toma remédio às 8h",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        solicitacao = PetsitterRequest.query.one()
        assert solicitacao.tutor_id == tutor_id
        assert solicitacao.status == "aberta"
        assert solicitacao.dias == 4
        assert [a.id for a in solicitacao.animais] == [animal_id]


def test_solicitar_sem_pet_nao_cria(app, client, monkeypatch):
    with app.app_context():
        tutor = _criar_tutor()
        db.session.commit()
        tutor_id = tutor.id

    login(monkeypatch, tutor_id)
    inicio = date.today() + timedelta(days=1)
    client.post(
        "/petsitter/solicitar",
        data={
            "data_inicio": inicio.isoformat(),
            "data_fim": inicio.isoformat(),
            "local_atendimento": "casa_sitter",
        },
    )
    with app.app_context():
        assert PetsitterRequest.query.count() == 0


def test_cancelar_solicitacao_de_outro_tutor_negado(app, client, monkeypatch):
    with app.app_context():
        tutor = _criar_tutor()
        intruso = _criar_tutor(name="Outro", email="outro@example.com")
        solicitacao = PetsitterRequest(
            tutor_id=tutor.id,
            data_inicio=date.today(),
            data_fim=date.today(),
        )
        db.session.add(solicitacao)
        db.session.commit()
        solicitacao_id, intruso_id = solicitacao.id, intruso.id

    login(monkeypatch, intruso_id)
    # Com Accept HTML o app devolve 403; em JSON ele converte para 404 (defense in depth).
    resp = client.post(
        f"/petsitter/solicitacao/{solicitacao_id}/cancelar",
        headers={"Accept": "text/html"},
    )
    assert resp.status_code == 403
    with app.app_context():
        assert db.session.get(PetsitterRequest, solicitacao_id).status == "aberta"


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

def test_admin_aprovar_candidatura_petsitter_cria_perfil(app, client, monkeypatch):
    with app.app_context():
        admin = _criar_tutor(name="Admin", email="admin@example.com", role="admin")
        sitter_user = _criar_tutor(name="Sitter", email="sitter@example.com")
        candidatura = CareerApplication(
            user_id=sitter_user.id,
            categoria="petsitter",
            nome="Sitter",
            email="sitter@example.com",
            cidade="Orlândia",
        )
        db.session.add(candidatura)
        db.session.commit()
        admin_id, candidatura_id, sitter_user_id = admin.id, candidatura.id, sitter_user.id

    login(monkeypatch, admin_id)
    resp = client.post(
        f"/petsitter/admin/candidatura/{candidatura_id}/aprovar",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        candidatura = db.session.get(CareerApplication, candidatura_id)
        assert candidatura.status == "aprovada"
        perfil = PetsitterProfile.query.filter_by(user_id=sitter_user_id).one()
        assert perfil.status == "aprovado"
        assert perfil.cidade == "Orlândia"


def test_admin_atribuir_sitter_a_solicitacao(app, client, monkeypatch):
    with app.app_context():
        admin = _criar_tutor(name="Admin", email="admin@example.com", role="admin")
        tutor = _criar_tutor(name="Tutor", email="tutor@example.com")
        sitter_user = _criar_tutor(name="Sitter", email="sitter@example.com")
        perfil = PetsitterProfile(user_id=sitter_user.id, status="aprovado")
        solicitacao = PetsitterRequest(
            tutor_id=tutor.id,
            data_inicio=date.today(),
            data_fim=date.today() + timedelta(days=2),
        )
        db.session.add_all([perfil, solicitacao])
        db.session.commit()
        admin_id, perfil_id, solicitacao_id = admin.id, perfil.id, solicitacao.id

    login(monkeypatch, admin_id)
    resp = client.post(
        f"/petsitter/admin/solicitacao/{solicitacao_id}/atribuir",
        data={"sitter_id": str(perfil_id)},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        solicitacao = db.session.get(PetsitterRequest, solicitacao_id)
        assert solicitacao.status == "atribuida"
        assert solicitacao.sitter_id == perfil_id


def test_painel_admin_exige_admin(app, client, monkeypatch):
    with app.app_context():
        tutor = _criar_tutor()
        db.session.commit()
        tutor_id = tutor.id

    login(monkeypatch, tutor_id)
    # Com Accept HTML o app devolve 403; em JSON ele converte para 404 (defense in depth).
    resp = client.get("/petsitter/admin", headers={"Accept": "text/html"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Indicações
# ---------------------------------------------------------------------------

def test_indicacao_gera_codigo_unico(app, client, monkeypatch):
    with app.app_context():
        tutor = _criar_tutor()
        db.session.commit()
        tutor_id = tutor.id

    login(monkeypatch, tutor_id)
    resp = client.get("/indicacao")
    assert resp.status_code == 200
    client.get("/indicacao")  # segunda visita não deve duplicar
    with app.app_context():
        codes = ReferralCode.query.filter_by(user_id=tutor_id).all()
        assert len(codes) == 1
        assert codes[0].code in resp.get_data(as_text=True)


def test_registro_captura_codigo_de_indicacao(app, client):
    with app.app_context():
        padrinho = _criar_tutor(name="Padrinho", email="padrinho@example.com")
        referral = ReferralCode.get_or_create(padrinho.id)
        db.session.commit()
        code = referral.code

    client.get(f"/register?ref={code}")
    with client.session_transaction() as sess:
        assert sess.get("referral_code") == code


def test_referral_signup_unico_por_usuario(app):
    with app.app_context():
        padrinho = _criar_tutor(name="Padrinho", email="padrinho@example.com")
        indicado = _criar_tutor(name="Indicado", email="indicado@example.com")
        referral = ReferralCode.get_or_create(padrinho.id)
        db.session.flush()
        db.session.add(
            ReferralSignup(code_id=referral.id, referred_user_id=indicado.id)
        )
        db.session.commit()
        assert len(referral.signups) == 1
