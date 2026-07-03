"""Fluxos de cadastro de parceiros: aprovação de clínica, convites e notificações."""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

import flask_login.utils as login_utils

from extensions import db
from models import Clinica, Notification, PartnerInvite, User, Veterinario
from models.petsitter import CareerApplication, PetsitterProfile


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def _make_user(name, email, role="adotante", phone=None):
    user = User(name=name, email=email, role=role, phone=phone)
    user.set_password("x")
    db.session.add(user)
    db.session.commit()
    return user


def _make_invite(tipo, **kwargs):
    token = secrets.token_urlsafe(24)
    invite = PartnerInvite(
        tipo=tipo,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        **kwargs,
    )
    db.session.add(invite)
    db.session.commit()
    return invite, token


def test_minha_clinica_cria_pendente_e_notifica_admin(app, client, monkeypatch):
    with app.app_context():
        admin = _make_user("Admin", "admin@example.com", role="admin")
        dono = _make_user("Dono", "dono@example.com")
        _login(monkeypatch, dono)

        resp = client.post("/minha-clinica", data={"nome": "Clínica Nova"})
        assert resp.status_code == 302

        clinica = Clinica.query.filter_by(nome="Clínica Nova").one()
        assert clinica.status == "pendente"

        aviso = Notification.query.filter_by(user_id=admin.id, kind="clinica_pendente").first()
        assert aviso is not None


def test_admin_aprova_clinica_e_avisa_dono(app, client, monkeypatch):
    with app.app_context():
        admin = _make_user("Admin", "admin2@example.com", role="admin")
        dono = _make_user("Dono", "dono2@example.com")
        clinica = Clinica(nome="Clínica Espera", owner_id=dono.id, status="pendente")
        db.session.add(clinica)
        db.session.commit()

        _login(monkeypatch, admin)
        resp = client.post(f"/admin/clinica/{clinica.id}/aprovar")
        assert resp.status_code == 302
        assert db.session.get(Clinica, clinica.id).status == "ativa"

        aviso = Notification.query.filter_by(user_id=dono.id, kind="clinica_aprovada").first()
        assert aviso is not None


def test_admin_parcerias_lista_pendencias(app, client, monkeypatch):
    with app.app_context():
        admin = _make_user("Admin", "admin3@example.com", role="admin")
        dono = _make_user("Dono", "dono3@example.com")
        db.session.add(Clinica(nome="Clínica Fila", owner_id=dono.id, status="pendente"))
        db.session.commit()

        _login(monkeypatch, admin)
        resp = client.get("/admin/parcerias")
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "Clínica Fila" in html
        assert "Convidar novo parceiro" in html


def test_convite_clinica_cria_conta_e_clinica_ativa(app, client):
    with app.app_context():
        invite, token = _make_invite("clinica", nome="Clínica Convidada", email="conv@example.com")

        resp = client.get(f"/convite/{token}")
        assert resp.status_code == 200

        resp = client.post(
            f"/convite/{token}",
            data={
                "nome": "Maria Dona",
                "email": "conv@example.com",
                "telefone": "16999990000",
                "estabelecimento_nome": "Clínica Convidada",
                "password": "senhaforte1",
                "password_confirmation": "senhaforte1",
            },
        )
        assert resp.status_code == 302

        usuario = User.query.filter_by(email="conv@example.com").one()
        clinica = Clinica.query.filter_by(nome="Clínica Convidada").one()
        assert clinica.status == "ativa"
        assert clinica.owner_id == usuario.id
        assert db.session.get(PartnerInvite, invite.id).used_at is not None


def test_convite_usado_redireciona_para_login(app, client):
    with app.app_context():
        invite, token = _make_invite("usuario")
        invite.used_at = datetime.now(timezone.utc)
        db.session.commit()

        resp = client.get(f"/convite/{token}")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


def test_convite_expirado_retorna_410(app, client):
    with app.app_context():
        invite, token = _make_invite("clinica")
        invite.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.session.commit()

        assert client.get(f"/convite/{token}").status_code == 410


def test_create_clinic_veterinario_exige_celular_e_nao_expoe_senha(app, client, monkeypatch):
    enviados = []

    with app.app_context():
        dono = _make_user("Dono", "dono4@example.com")
        clinica = Clinica(nome="Clínica Vet", owner_id=dono.id, status="ativa")
        db.session.add(clinica)
        db.session.commit()

        import app as appmod
        monkeypatch.setattr(appmod.mail, "send", lambda msg: enviados.append(msg))

        _login(monkeypatch, dono)

        # sem celular → recusa
        resp = client.post(
            f"/clinica/{clinica.id}/veterinario",
            data={"name": "Vet Novo", "email": "vet.novo@example.com", "crmv": "SP-1234"},
        )
        assert resp.status_code == 302
        assert User.query.filter_by(email="vet.novo@example.com").first() is None

        # com celular → cria e envia link de primeiro acesso por e-mail
        resp = client.post(
            f"/clinica/{clinica.id}/veterinario",
            data={
                "name": "Vet Novo",
                "email": "vet.novo@example.com",
                "crmv": "SP-1234",
                "phone": "16988887777",
            },
        )
        assert resp.status_code == 302
        vet_user = User.query.filter_by(email="vet.novo@example.com").one()
        assert vet_user.phone
        assert Veterinario.query.filter_by(user_id=vet_user.id).one().crmv == "SP-1234"
        assert len(enviados) == 1
        assert "/primeiro-acesso" in enviados[0].body or "first" in enviados[0].body or "token=" in enviados[0].body


def test_aprovar_candidatura_petsitter_cria_usuario(app, client, monkeypatch):
    with app.app_context():
        admin = _make_user("Admin", "admin5@example.com", role="admin")
        candidatura = CareerApplication(
            categoria="petsitter",
            nome="Cuidadora Ana",
            email="ana.sitter@example.com",
            telefone="16977776666",
        )
        db.session.add(candidatura)
        db.session.commit()

        _login(monkeypatch, admin)
        resp = client.post(f"/petsitter/admin/candidatura/{candidatura.id}/aprovar")
        assert resp.status_code == 302

        usuario = User.query.filter_by(email="ana.sitter@example.com").one()
        perfil = PetsitterProfile.query.filter_by(user_id=usuario.id).one()
        assert perfil.status == "aprovado"


def test_aprovar_candidatura_clinica_gera_convite(app, client, monkeypatch):
    with app.app_context():
        admin = _make_user("Admin", "admin6@example.com", role="admin")
        candidatura = CareerApplication(
            categoria="clinica",
            nome="Clínica Candidata",
            email="clinica.cand@example.com",
        )
        db.session.add(candidatura)
        db.session.commit()

        _login(monkeypatch, admin)
        resp = client.post(f"/petsitter/admin/candidatura/{candidatura.id}/aprovar")
        assert resp.status_code == 302

        convite = PartnerInvite.query.filter_by(email="clinica.cand@example.com").one()
        assert convite.tipo == "clinica"
        assert User.query.filter_by(email="clinica.cand@example.com").first() is not None
