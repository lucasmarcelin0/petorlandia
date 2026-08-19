"""Primeiro acesso e portas de entrada do visitante.

Quem chega na PetOrlandia quase nunca chega pela home: vem de um link de
carteirinha, de uma receita, de um tratamento ou de uma busca no Google. Estes
testes travam as duas garantias que fazem essa chegada funcionar — a tela de
primeiro acesso reconhece de onde a pessoa veio, e o botao de acao da navbar
nao empurra tutor para dentro da area de gestao de clinica.
"""

from datetime import datetime, timedelta

import pytest

from extensions import db
from models import Animal, User
from models.clinica import Clinica, ExternalOnboardingInvite
from time_utils import BR_TZ


def _make_invite(*, tutor_name="Maria Silva", pet_name="Rex", clinic_name="Clinica Amigo Fiel"):
    """Convite de tutor completo: pessoa, pet e clinica que enviou."""
    tutor = User(name=tutor_name, email=f"{tutor_name.split()[0].lower()}@test", role="adotante")
    tutor.set_password("x")
    tutor.phone = "16999990000"
    db.session.add(tutor)

    clinica = Clinica(nome=clinic_name)
    db.session.add(clinica)
    db.session.flush()

    animal = Animal(name=pet_name, user_id=tutor.id)
    db.session.add(animal)
    db.session.flush()

    invite = ExternalOnboardingInvite(
        token="convite-teste-123",
        invite_type="tutor",
        tutor_id=tutor.id,
        animal_id=animal.id,
        clinica_id=clinica.id,
        expires_at=datetime.now(BR_TZ) + timedelta(days=7),
    )
    db.session.add(invite)
    db.session.commit()
    return invite


def test_primeiro_acesso_sem_contexto_ainda_acolhe(app):
    """Sem token, a tela nao pode virar um formulario anonimo e seco."""
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

    response = client.get("/primeiro-acesso")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Bem-vindo à PetOrlândia" in body
    # As tres promessas que tiram o medo de cadastrar.
    assert "Gratuito para tutores, sem cartão." in body
    assert "Os dados do seu pet são seus." in body
    assert "Avisamos quando o reforço estiver perto." in body


def test_primeiro_acesso_com_convite_chama_pelo_nome(app):
    """Com convite, a tela continua a conversa: nomeia pessoa, pet e clinica."""
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        _make_invite()

    response = client.get("/primeiro-acesso?token=convite-teste-123")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    # Primeiro nome apenas — "Olá, Maria!" e nao "Olá, Maria Silva!".
    assert "Olá, Maria!" in body
    assert "Maria Silva" not in body
    assert "Rex" in body
    assert "Clinica Amigo Fiel" in body


def test_primeiro_acesso_com_token_invalido_nao_quebra(app):
    """Token expirado ou forjado degrada para a versao generica, sem erro."""
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

    response = client.get("/primeiro-acesso?token=nao-existe")

    assert response.status_code == 200
    assert "Bem-vindo à PetOrlândia" in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "path, espera_trial",
    [
        ("/", False),
        ("/para-tutores", False),
        ("/servicos", False),
        ("/parceiros/clinica", True),
        ("/precos", True),
    ],
)
def test_cta_da_navbar_segue_a_intencao_da_pagina(app, path, espera_trial):
    """O botao de acao muda com a area.

    Em area de clinica ele vende o teste do sistema; em qualquer outra ele
    oferece a conta gratuita. Antes, "Testar gratis" mandava todo mundo para
    ``minha_clinica`` — inclusive o tutor que veio da carteirinha do pet.
    """
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

    response = client.get(path)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    if espera_trial:
        assert "Testar grátis" in body
        assert "cta_nav_trial" in body
    else:
        assert "Criar conta grátis" in body
        assert "cta_nav_signup" in body
        # O tutor nao pode ser levado para a area de gestao de clinica.
        assert "cta_nav_trial" not in body


def test_menu_publico_oferece_a_porta_do_tutor(app):
    """/para-tutores existe desde sempre, mas estava orfa no menu."""
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Para tutores" in body
    assert "/para-tutores" in body
    # O selo de gratuidade aparece sem precisar clicar.
    assert "nav-badge-free" in body
    # A porta B2B continua no lugar.
    assert "Para clínicas" in body
