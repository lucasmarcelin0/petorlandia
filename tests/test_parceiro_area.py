import os

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

import flask_login.utils as login_utils

from extensions import db
from models import User, Clinica, CasaDeRacao
from models.petsitter import PetsitterProfile


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def _make_user(name, email, role="adotante"):
    user = User(name=name, email=email, role=role)
    user.set_password("x")
    db.session.add(user)
    db.session.commit()
    return user


def test_dashboard_requires_parceiro_role(app, client, monkeypatch):
    with app.app_context():
        adotante = _make_user("Comum", "comum@example.com", role="adotante")
        _login(monkeypatch, adotante)
        # Acesso negado: o app converte 403 -> 404 (defense-in-depth) quando o
        # cliente não pede HTML explicitamente.
        assert client.get("/parceiro").status_code in (403, 404)

        parceiro = _make_user("Parceiro", "parceiro@example.com", role="parceiro")
        _login(monkeypatch, parceiro)
        assert client.get("/parceiro").status_code == 200


def test_parceiro_cria_casa_de_racao_ativa_com_dono_novo(app, client, monkeypatch):
    with app.app_context():
        parceiro = _make_user("Parceiro", "p1@example.com", role="parceiro")
        _login(monkeypatch, parceiro)

        resp = client.post(
            "/parceiro/estabelecimentos/novo",
            data={
                "tipo": "casa_de_racao",
                "nome": "Ração Feliz",
                "owner_mode": "new",
                "owner_name": "Dona Loja",
                "owner_email": "dona.loja@example.com",
            },
        )
        assert resp.status_code == 302

        casa = CasaDeRacao.query.filter_by(nome="Ração Feliz").one()
        owner = User.query.filter_by(email="dona.loja@example.com").one()
        assert casa.status == "ativa"
        assert casa.tipo == "casa_de_racao"
        assert casa.owner_id == owner.id
        assert casa.registered_by_id == parceiro.id
        # dono novo registrado como adicionado pelo parceiro
        assert owner.added_by_id == parceiro.id


def test_parceiro_cria_petshop_tipo_preservado(app, client, monkeypatch):
    with app.app_context():
        parceiro = _make_user("Parceiro", "p-petshop@example.com", role="parceiro")
        _login(monkeypatch, parceiro)

        resp = client.post(
            "/parceiro/estabelecimentos/novo",
            data={
                "tipo": "petshop",
                "nome": "Pet Shop Auau",
                "owner_mode": "self",
            },
        )
        assert resp.status_code == 302
        casa = CasaDeRacao.query.filter_by(nome="Pet Shop Auau").one()
        assert casa.tipo == "petshop"
        assert casa.status == "ativa"
        assert casa.owner_id == parceiro.id
        assert casa.registered_by_id == parceiro.id


def test_parceiro_cria_clinica_dono_existente(app, client, monkeypatch):
    with app.app_context():
        parceiro = _make_user("Parceiro", "p2@example.com", role="parceiro")
        dono = _make_user("Dono Clínica", "dono.clinica@example.com")
        _login(monkeypatch, parceiro)

        resp = client.post(
            "/parceiro/estabelecimentos/novo",
            data={
                "tipo": "clinica",
                "nome": "Clínica VidaPet",
                "owner_mode": "existing",
                "owner_email": "dono.clinica@example.com",
            },
        )
        assert resp.status_code == 302

        clinica = Clinica.query.filter_by(nome="Clínica VidaPet").one()
        assert clinica.owner_id == dono.id
        assert clinica.registered_by_id == parceiro.id
        # o dono passa a enxergar a clínica como sua
        assert db.session.get(User, dono.id).clinica_id == clinica.id


def test_parceiro_cria_petsitter_aprovado(app, client, monkeypatch):
    with app.app_context():
        parceiro = _make_user("Parceiro", "p3@example.com", role="parceiro")
        _login(monkeypatch, parceiro)

        resp = client.post(
            "/parceiro/estabelecimentos/novo",
            data={
                "tipo": "petsitter",
                "nome": "Cuidados do João",
                "cidade": "Orlândia",
                "owner_mode": "new",
                "owner_name": "João Sitter",
                "owner_email": "joao.sitter@example.com",
            },
        )
        assert resp.status_code == 302

        owner = User.query.filter_by(email="joao.sitter@example.com").one()
        sitter = PetsitterProfile.query.filter_by(user_id=owner.id).one()
        assert sitter.status == "aprovado"
        assert sitter.registered_by_id == parceiro.id
        assert sitter.cidade == "Orlândia"


def test_parceiro_cria_usuario_avulso(app, client, monkeypatch):
    with app.app_context():
        parceiro = _make_user("Parceiro", "p4@example.com", role="parceiro")
        _login(monkeypatch, parceiro)

        resp = client.post(
            "/parceiro/usuarios/novo",
            data={
                "name": "Cliente Novo",
                "email": "cliente.novo@example.com",
                "phone": "(16) 99999-1111",
            },
        )
        assert resp.status_code == 302

        novo = User.query.filter_by(email="cliente.novo@example.com").one()
        assert novo.added_by_id == parceiro.id
        assert novo.role == "adotante"


def test_parceiro_acessa_loja_que_cadastrou(app, client, monkeypatch):
    """O gate de acesso libera o parceiro a gerenciar o que cadastrou,
    mesmo que o dono seja outro usuário."""
    with app.app_context():
        parceiro = _make_user("Parceiro", "p5@example.com", role="parceiro")
        dono = _make_user("Dono", "dono5@example.com")
        casa = CasaDeRacao(
            nome="Loja Cadastrada",
            owner_id=dono.id,
            registered_by_id=parceiro.id,
            status="ativa",
        )
        db.session.add(casa)
        db.session.commit()

        _login(monkeypatch, parceiro)
        # produtos chama _casa_loja_access; acesso liberado pelo registered_by_id.
        # (acesso negado retornaria 404 pelo handler de HTTPException)
        resp = client.get(f"/casa-de-racao/{casa.id}/produtos")
        assert resp.status_code == 200
