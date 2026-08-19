"""Aprovar candidatura tem que dar acesso de verdade, não um beco sem saída.

Fluxo real que estava quebrado (categorias clinica/petshop/laboratorio/
especialista, em `petsitter_admin_candidatura`):

1. o admin aprova a candidatura em /admin/parcerias;
2. a aprovação **cria a conta** do candidato com senha aleatória (uuid4) e
   manda um PartnerInvite por e-mail;
3. o candidato abre o convite deslogado e recebe "Este e-mail já tem conta.
   Entre primeiro e abra o link do convite de novo.";
4. ele não consegue entrar, porque nunca teve senha — o e-mail dessas
   categorias não leva link de primeiro acesso (só o de petsitter leva).

Ou seja: a conta pré-criada bloqueava o convite dela mesma, e aprovar não
liberava acesso nenhum. Agora o convite adota essa conta e define a senha.

A adoção é amarrada ao `invite.email`. O teste de sequestro abaixo é o que
impede alguém com um convite válido de trocar a senha da conta de outra
pessoa digitando outro endereço no formulário.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from extensions import db
from models import CasaDeRacao, Clinica, PartnerInvite, User, Veterinario

SENHA = "senhaforte123"
EMAIL_CONVIDADO = "candidato.aprovado@exemplo.com"


@pytest.fixture()
def invite_app(app):
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["MAIL_SUPPRESS_SEND"] = True
    return app


def _admin():
    admin = User(name="Admin", email="admin@exemplo.com", role="admin", worker="veterinario")
    admin.set_password("x")
    db.session.add(admin)
    db.session.commit()
    return admin


def _conta_pre_criada(email=EMAIL_CONVIDADO, telefone="+5531999998888"):
    """Reproduz o que a aprovação de candidatura deixa no banco."""
    usuario = User(name="Fulano da Silva", email=email, phone=telefone)
    usuario.set_password(secrets.token_hex(16))  # senha aleatória, inutilizável
    db.session.add(usuario)
    db.session.commit()
    return usuario


def _criar_convite(admin, tipo, email=EMAIL_CONVIDADO, telefone="+5531999998888"):
    token = secrets.token_urlsafe(24)
    db.session.add(
        PartnerInvite(
            tipo=tipo,
            nome="Fulano da Silva",
            email=email,
            telefone=telefone,
            cidade="Belo Horizonte",
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            created_by_id=admin.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
    )
    db.session.commit()
    return token


def _submeter(client, token, **extra):
    payload = {
        "nome": "Fulano da Silva",
        "email": EMAIL_CONVIDADO,
        "telefone": "+5531999998888",
        "password": SENHA,
        "password_confirmation": SENHA,
    }
    payload.update(extra)
    return client.post(f"/convite/{token}", data=payload, follow_redirects=True)


def test_convite_de_clinica_adota_conta_pre_criada(invite_app, client):
    """O caso do print: candidatura de clínica aprovada."""
    admin = _admin()
    usuario = _conta_pre_criada()
    user_id = usuario.id
    token = _criar_convite(admin, "clinica")

    resposta = _submeter(client, token, estabelecimento_nome="Clínica do Fulano")

    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert "já tem conta" not in corpo, "convite ainda bloqueia a conta pré-criada"

    clinica = Clinica.query.filter_by(nome="Clínica do Fulano").first()
    assert clinica is not None, "clínica não foi criada"
    assert clinica.owner_id == user_id

    usuario = db.session.get(User, user_id)
    assert usuario.check_password(SENHA), "candidato continua sem senha utilizável"
    assert usuario.clinica_id == clinica.id


def test_convite_marca_uso_e_nao_serve_duas_vezes(invite_app, client):
    admin = _admin()
    _conta_pre_criada()
    token = _criar_convite(admin, "clinica")

    _submeter(client, token, estabelecimento_nome="Clínica do Fulano")

    invite = PartnerInvite.query.first()
    assert invite.used_at is not None, "convite não foi marcado como usado"

    client.get("/logout")
    segunda = client.post(
        f"/convite/{token}",
        data={"nome": "X", "email": EMAIL_CONVIDADO, "telefone": "+5531999998888",
              "estabelecimento_nome": "Outra", "password": SENHA,
              "password_confirmation": SENHA},
        follow_redirects=True,
    )
    assert Clinica.query.count() == 1, "convite usado criou um segundo estabelecimento"
    assert segunda.status_code == 200


def test_convite_de_petshop_cria_casa_de_racao(invite_app, client):
    admin = _admin()
    usuario = _conta_pre_criada()
    user_id = usuario.id
    token = _criar_convite(admin, "casa_de_racao")

    _submeter(client, token, estabelecimento_nome="Ração do Fulano")

    casa = CasaDeRacao.query.filter_by(nome="Ração do Fulano").first()
    assert casa is not None
    assert casa.owner_id == user_id
    assert db.session.get(User, user_id).check_password(SENHA)


def test_convite_de_veterinario_ainda_exige_crmv(invite_app, client):
    """Decisão de produto: acesso de veterinário só com CRMV informado."""
    admin = _admin()
    _conta_pre_criada()
    token = _criar_convite(admin, "veterinario")

    sem_crmv = _submeter(client, token)
    assert Veterinario.query.count() == 0, "criou veterinário sem CRMV"
    assert "CRMV" in sem_crmv.get_data(as_text=True)

    com_crmv = _submeter(client, token, crmv="MG-12345")
    assert com_crmv.status_code == 200
    vet = Veterinario.query.first()
    assert vet is not None and vet.crmv == "MG-12345"


def test_convite_nao_permite_sequestrar_conta_de_outro_email(invite_app, client):
    """Trava de segurança da adoção.

    Quem tem um convite válido não pode digitar o e-mail de outra pessoa e
    assumir a conta dela. A adoção olha o invite.email, nunca o do formulário.
    """
    admin = _admin()
    vitima = User(name="Vítima", email="vitima@exemplo.com", phone="+5531911112222")
    vitima.set_password("senha-original-da-vitima")
    db.session.add(vitima)
    db.session.commit()
    vitima_id = vitima.id

    token = _criar_convite(admin, "clinica")  # convite emitido para outro e-mail

    resposta = client.post(
        f"/convite/{token}",
        data={
            "nome": "Atacante",
            "email": "vitima@exemplo.com",  # e-mail de terceiro
            "telefone": "+5531933334444",
            "estabelecimento_nome": "Clínica Tomada",
            "password": "senha-do-atacante",
            "password_confirmation": "senha-do-atacante",
        },
        follow_redirects=True,
    )

    assert resposta.status_code == 200
    vitima = db.session.get(User, vitima_id)
    assert vitima.check_password("senha-original-da-vitima"), (
        "convite trocou a senha da conta de outra pessoa"
    )
    assert not vitima.check_password("senha-do-atacante")
    assert Clinica.query.filter_by(owner_id=vitima_id).count() == 0


def test_aprovar_candidatura_de_clinica_leva_a_acesso_real(invite_app, client, monkeypatch):
    """Ponta a ponta: admin aprova em /admin/parcerias e o candidato entra.

    Este é o requisito de verdade — aprovar tem que resultar em acesso, não em
    um convite que morre na validação. O token só existe em hash no banco, então
    fixamos o gerador para conseguir abrir o link como o candidato abriria.
    """
    import secrets as secrets_module

    from models import CareerApplication

    admin = _admin()
    candidatura = CareerApplication(
        nome="Fulano da Silva",
        email=EMAIL_CONVIDADO,
        telefone="+5531999998888",
        cidade="Belo Horizonte",
        categoria="clinica",
        status="pendente",
    )
    db.session.add(candidatura)
    db.session.commit()
    candidatura_id = candidatura.id

    token_fixo = "token-previsivel-para-teste"
    monkeypatch.setattr(secrets_module, "token_urlsafe", lambda *_a, **_kw: token_fixo)

    with client.session_transaction() as sessao:
        sessao.clear()
        sessao["_user_id"] = str(admin.id)
        sessao["_fresh"] = True
    aprovacao = client.post(
        f"/petsitter/admin/candidatura/{candidatura_id}/aprovar", follow_redirects=True
    )
    assert aprovacao.status_code == 200
    assert db.session.get(CareerApplication, candidatura_id).status == "aprovada"

    # Agora o candidato, deslogado, abre o link que recebeu por e-mail.
    client.get("/logout")
    candidato = invite_app.test_client()
    conclusao = candidato.post(
        f"/convite/{token_fixo}",
        data={
            "nome": "Fulano da Silva",
            "email": EMAIL_CONVIDADO,
            "telefone": "+5531999998888",
            "estabelecimento_nome": "Clínica do Fulano",
            "password": SENHA,
            "password_confirmation": SENHA,
        },
        follow_redirects=True,
    )

    assert conclusao.status_code == 200
    assert "já tem conta" not in conclusao.get_data(as_text=True)

    usuario = User.query.filter_by(email=EMAIL_CONVIDADO).first()
    clinica = Clinica.query.filter_by(nome="Clínica do Fulano").first()
    assert clinica is not None, "aprovar não resultou em clínica"
    assert clinica.owner_id == usuario.id
    assert usuario.clinica_id == clinica.id
    assert usuario.check_password(SENHA), "candidato terminou sem senha utilizável"


def test_convite_ainda_cria_conta_nova_quando_nao_existe(invite_app, client):
    """Convite avulso (sem candidatura) continua funcionando como antes."""
    admin = _admin()
    token = _criar_convite(admin, "clinica")

    _submeter(client, token, estabelecimento_nome="Clínica Nova")

    usuario = User.query.filter_by(email=EMAIL_CONVIDADO).first()
    assert usuario is not None
    assert usuario.check_password(SENHA)
    assert Clinica.query.filter_by(nome="Clínica Nova").count() == 1
