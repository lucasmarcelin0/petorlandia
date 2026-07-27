"""Estagiário usa o sistema inteiro, mas nunca assina ato veterinário.

O risco que estes testes guardam é concreto: se um estagiário sem CRMV puder
carregar um número no perfil — ou se um documento imprimir um CRMV que não
existe — a clínica emite papel com registro falso.
"""

from __future__ import annotations

import pytest

from extensions import db
from models import Clinica, User, Veterinario
from models.usuarios import HABILITACAO_CRMV, HABILITACAO_ESTAGIARIO


PASSWORD = "Senha@123"


def _make_user(email, name, role="adotante", worker=None):
    user = User(name=name, email=email, role=role, worker=worker, phone="16999990000")
    user.set_password(PASSWORD)
    return user


def _login(client, email):
    resp = client.post(
        "/login", data={"login": email, "password": PASSWORD}, follow_redirects=False
    )
    assert resp.status_code in {200, 302}


@pytest.fixture()
def equipe(app):
    with app.app_context():
        dona = _make_user("dona.estagio@test.com", "Dona Clinica", role="veterinario", worker="veterinario")
        est_user = _make_user("laiane.estagio@test.com", "Laiane Stefani", role="veterinario", worker="veterinario")
        db.session.add_all([dona, est_user])
        db.session.flush()

        clinica = Clinica(nome="Clinica Escola", owner_id=dona.id)
        db.session.add(clinica)
        db.session.flush()
        dona.clinica_id = clinica.id
        est_user.clinica_id = clinica.id

        supervisora = Veterinario(
            user=dona, crmv="65152", crmv_estado="SP", clinica_id=clinica.id
        )
        db.session.add(supervisora)
        db.session.flush()

        estagiaria = Veterinario(
            user=est_user,
            crmv=None,
            clinica_id=clinica.id,
            habilitacao=HABILITACAO_ESTAGIARIO,
            supervisor_id=supervisora.id,
        )
        db.session.add(estagiaria)
        db.session.commit()

        yield {
            "clinica_id": clinica.id,
            "supervisora_id": supervisora.id,
            "estagiaria_id": estagiaria.id,
            "dona_email": dona.email,
            "estagiaria_email": est_user.email,
        }


def test_estagiaria_nao_tem_crmv_e_nao_assina(app, equipe):
    with app.app_context():
        est = db.session.get(Veterinario, equipe["estagiaria_id"])
        assert est.is_estagiario is True
        assert est.pode_assinar is False
        # O ponto crítico: a UI nunca recebe um número para exibir.
        assert est.crmv_exibicao is None


def test_documento_da_estagiaria_leva_crmv_do_supervisor(app, equipe):
    with app.app_context():
        est = db.session.get(Veterinario, equipe["estagiaria_id"])
        assinatura = est.assinatura
        assert assinatura.pode_assinar is False
        assert assinatura.crmv_formatado == "CRMV 65152/SP"
        assert assinatura.responsavel_tecnico == "Dona Clinica"
        assert "Estagiário(a)" in assinatura.linha_completa
        assert "sob supervisão de Dona Clinica" in assinatura.linha_completa


def test_estagiaria_sem_supervisor_nao_produz_crmv_nenhum(app, equipe):
    """Falha segura: sem supervisor válido, nenhum número vai para o papel."""
    with app.app_context():
        est = db.session.get(Veterinario, equipe["estagiaria_id"])
        est.supervisor_id = None
        db.session.commit()
        assinatura = est.assinatura
        assert assinatura.crmv_formatado is None
        assert assinatura.responsavel_tecnico == "Laiane Stefani"


def test_veterinaria_com_crmv_assina_normalmente(app, equipe):
    with app.app_context():
        vet = db.session.get(Veterinario, equipe["supervisora_id"])
        assert vet.pode_assinar is True
        assert vet.crmv_exibicao == "65152/SP"
        assert vet.assinatura.crmv_formatado == "CRMV 65152/SP"


def test_estagiaria_nao_pode_se_promover_editando_o_proprio_perfil(client, app, equipe):
    """Autopromoção é o pior cenário: estagiária virando 'vet com CRMV'."""
    _login(client, equipe["estagiaria_email"])
    prefix = f"vetprofile_{equipe['estagiaria_id']}"
    resp = client.post(
        f"/veterinario/{equipe['estagiaria_id']}/profile",
        data={
            f"{prefix}-name": "Laiane Stefani",
            f"{prefix}-habilitacao": HABILITACAO_CRMV,
            f"{prefix}-crmv": "999999",
            f"{prefix}-crmv_estado": "SP",
            f"{prefix}-cidades_atendidas": "",
            "next": "/",
        },
    )
    assert resp.status_code in (302, 403, 404)
    with app.app_context():
        est = db.session.get(Veterinario, equipe["estagiaria_id"])
        assert est.is_estagiario is True
        assert est.crmv is None


def test_dona_da_clinica_promove_estagiaria_com_crmv_real(client, app, equipe):
    _login(client, equipe["dona_email"])
    prefix = f"vetprofile_{equipe['estagiaria_id']}"
    resp = client.post(
        f"/veterinario/{equipe['estagiaria_id']}/profile",
        data={
            f"{prefix}-name": "Laiane Stefani",
            f"{prefix}-habilitacao": HABILITACAO_CRMV,
            f"{prefix}-crmv": "99999",
            f"{prefix}-crmv_estado": "SP",
            f"{prefix}-cidades_atendidas": "",
            "next": "/",
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        est = db.session.get(Veterinario, equipe["estagiaria_id"])
        assert est.is_estagiario is False
        assert est.pode_assinar is True
        assert est.crmv == "99999"
        assert est.supervisor_id is None


def test_marcar_como_estagiario_exige_supervisor(client, app, equipe):
    _login(client, equipe["dona_email"])
    vet_id = equipe["supervisora_id"]
    prefix = f"vetprofile_{vet_id}"
    resp = client.post(
        f"/veterinario/{vet_id}/profile",
        data={
            f"{prefix}-name": "Dona Clinica",
            f"{prefix}-habilitacao": HABILITACAO_ESTAGIARIO,
            f"{prefix}-supervisor_id": "0",
            f"{prefix}-cidades_atendidas": "",
            "next": "/",
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        vet = db.session.get(Veterinario, vet_id)
        # Nada mudou: sem supervisor o formulário não valida.
        assert vet.is_estagiario is False
        assert vet.crmv == "65152"


def test_estagiaria_fica_fora_da_vitrine_publica(app, equipe):
    from app import _is_public_veterinarian

    with app.app_context():
        est = db.session.get(Veterinario, equipe["estagiaria_id"])
        assert _is_public_veterinarian(est) is False


def test_card_da_equipe_mostra_supervisao_e_nao_crmv(client, app, equipe):
    _login(client, equipe["dona_email"])
    resp = client.get(f"/clinica/{equipe['clinica_id']}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Estagiário(a)" in html
    assert "Supervisão: Dona Clinica (CRMV 65152/SP)" in html
