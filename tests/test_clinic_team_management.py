"""Gestão da equipe pela aba "Veterinários" do painel da clínica.

Cobre o que o dono da clínica precisa fazer sem sair da aba: editar os dados
de um profissional e alterar os horários de trabalho já cadastrados.
"""

from __future__ import annotations

from datetime import time as dtime

import pytest

from extensions import db
from models import Clinica, User, Veterinario, VetSchedule


PASSWORD = "Senha@123"


def _make_user(email, name, role="adotante", worker=None):
    user = User(name=name, email=email, role=role, worker=worker, phone="16999990000")
    user.set_password(PASSWORD)
    return user


def _login(client, email):
    resp = client.post(
        "/login",
        data={"email": email, "password": PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code in {200, 302}


@pytest.fixture()
def team_seed(app):
    with app.app_context():
        owner = _make_user("dona.clinica@test.com", "Dona da Clinica")
        vet_user = _make_user(
            "vet.equipe@test.com",
            "Vet Equipe",
            role="veterinario",
            worker="veterinario",
        )
        intruso = _make_user("intruso@test.com", "Intruso")
        db.session.add_all([owner, vet_user, intruso])
        db.session.flush()

        clinica = Clinica(nome="Clinica Equipe", owner_id=owner.id)
        db.session.add(clinica)
        db.session.flush()

        owner.clinica_id = clinica.id
        vet_user.clinica_id = clinica.id
        vet = Veterinario(user=vet_user, crmv="12345", clinica_id=clinica.id)
        db.session.add(vet)
        db.session.flush()

        horario = VetSchedule(
            veterinario_id=vet.id,
            dia_semana="Segunda",
            hora_inicio=dtime(7, 0),
            hora_fim=dtime(13, 0),
        )
        db.session.add(horario)
        db.session.commit()

        yield {
            "clinica_id": clinica.id,
            "vet_id": vet.id,
            "vet_user_id": vet_user.id,
            "horario_id": horario.id,
            "owner_email": owner.email,
            "intruso_email": intruso.email,
        }


def _edit_url(seed):
    return (
        f"/clinica/{seed['clinica_id']}/veterinario/{seed['vet_id']}"
        f"/schedule/{seed['horario_id']}/edit"
    )


def test_dona_ve_acoes_de_edicao_na_aba_equipe(client, team_seed):
    _login(client, team_seed["owner_email"])
    resp = client.get(f"/clinica/{team_seed['clinica_id']}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Editar dados" in html
    assert "Editar horários" in html
    assert _edit_url(team_seed) in html


def test_dona_altera_horario_existente(client, app, team_seed):
    _login(client, team_seed["owner_email"])
    resp = client.post(
        _edit_url(team_seed),
        data={
            "dia_semana": "Quarta",
            "hora_inicio": "08:00",
            "hora_fim": "18:00",
            "intervalo_inicio": "12:00",
            "intervalo_fim": "13:00",
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        horario = db.session.get(VetSchedule, team_seed["horario_id"])
        assert horario.dia_semana == "Quarta"
        assert horario.hora_inicio == dtime(8, 0)
        assert horario.hora_fim == dtime(18, 0)
        assert horario.intervalo_inicio == dtime(12, 0)
        assert horario.intervalo_fim == dtime(13, 0)


@pytest.mark.parametrize(
    "payload",
    [
        {"dia_semana": "Domingo", "hora_inicio": "18:00", "hora_fim": "08:00"},
        {"dia_semana": "Sexta-feira", "hora_inicio": "08:00", "hora_fim": "18:00"},
        {
            "dia_semana": "Segunda",
            "hora_inicio": "08:00",
            "hora_fim": "18:00",
            "intervalo_inicio": "19:00",
            "intervalo_fim": "20:00",
        },
    ],
    ids=["fim_antes_do_inicio", "dia_invalido", "intervalo_fora_do_expediente"],
)
def test_horario_invalido_nao_altera_nada(client, app, team_seed, payload):
    _login(client, team_seed["owner_email"])
    resp = client.post(_edit_url(team_seed), data=payload)
    assert resp.status_code == 302
    with app.app_context():
        horario = db.session.get(VetSchedule, team_seed["horario_id"])
        assert horario.dia_semana == "Segunda"
        assert horario.hora_inicio == dtime(7, 0)
        assert horario.hora_fim == dtime(13, 0)


def test_usuario_sem_vinculo_nao_altera_horario(client, app, team_seed):
    _login(client, team_seed["intruso_email"])
    resp = client.post(
        _edit_url(team_seed),
        data={"dia_semana": "Quarta", "hora_inicio": "08:00", "hora_fim": "18:00"},
        headers={"Accept": "text/html"},
    )
    # O handler de HTTPException devolve 404 no lugar de 403 fora de HTML.
    assert resp.status_code in (403, 404)
    with app.app_context():
        horario = db.session.get(VetSchedule, team_seed["horario_id"])
        assert horario.dia_semana == "Segunda"


def test_dona_edita_dados_do_profissional(client, app, team_seed):
    _login(client, team_seed["owner_email"])
    prefix = f"vetprofile_{team_seed['vet_id']}"
    resp = client.post(
        f"/veterinario/{team_seed['vet_id']}/profile",
        data={
            f"{prefix}-name": "Vet Equipe Renomeada",
            f"{prefix}-crmv": "99999",
            f"{prefix}-crmv_estado": "SP",
            f"{prefix}-phone": "16988887777",
            f"{prefix}-cidades_atendidas": "",
            "next": f"/clinica/{team_seed['clinica_id']}",
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        vet = db.session.get(Veterinario, team_seed["vet_id"])
        assert vet.crmv == "99999"
        assert vet.user.name == "Vet Equipe Renomeada"


def test_usuario_sem_vinculo_nao_edita_perfil(client, app, team_seed):
    _login(client, team_seed["intruso_email"])
    prefix = f"vetprofile_{team_seed['vet_id']}"
    resp = client.post(
        f"/veterinario/{team_seed['vet_id']}/profile",
        data={
            f"{prefix}-name": "Invadido",
            f"{prefix}-crmv": "00000",
            "next": "/",
        },
        headers={"Accept": "text/html"},
    )
    assert resp.status_code in (403, 404)
    with app.app_context():
        vet = db.session.get(Veterinario, team_seed["vet_id"])
        assert vet.crmv == "12345"
