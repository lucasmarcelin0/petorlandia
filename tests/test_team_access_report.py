"""Quadro "o que esta pessoa consegue fazer hoje" da equipe da clínica.

O quadro só lê permissões, usando as mesmas funções das rotas; os testes
garantem que ele acompanha o comportamento real (estagiário supervisionado,
supervisor vencido, permissão de estoque) e aparece só para o dono.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from flask import g

from extensions import db
from helpers import ensure_veterinarian_membership
from models import ClinicStaff, Clinica, User, Veterinario
from scripts.auditar_acessos_equipe import linhas_relatorio
from services.team_access import access_report
from time_utils import utcnow


def _membership(vet, *, active=True):
    membership = ensure_veterinarian_membership(vet)
    db.session.flush()
    now = utcnow()
    membership.started_at = now - timedelta(days=90)
    membership.trial_ends_at = now + timedelta(days=60) if active else now - timedelta(days=30)
    membership.paid_until = None
    return membership


@pytest.fixture
def equipe(app):
    clinic = Clinica(nome="Clínica Escola")
    sup_u = User(name="Dr. Supervisor", email="sup@acesso.local", worker="veterinario")
    est_u = User(name="Laiane Estagiária", email="laiane@acesso.local", worker="colaborador", role="vacinador")
    col_u = User(name="Colaborador Novo", email="col@acesso.local", worker="colaborador")
    for user in (sup_u, est_u, col_u):
        user.set_password("x")
    db.session.add_all([clinic, sup_u, est_u, col_u])
    db.session.flush()
    clinic.owner_id = sup_u.id
    for user in (sup_u, est_u, col_u):
        user.clinica_id = clinic.id
    sup = Veterinario(user=sup_u, crmv="65152", crmv_estado="SP", clinica_id=clinic.id)
    db.session.add(sup)
    db.session.flush()
    est = Veterinario(user=est_u, crmv=None, clinica_id=clinic.id, habilitacao="estagiario", supervisor_id=sup.id)
    db.session.add(est)
    db.session.flush()
    _membership(sup)
    db.session.add_all([
        ClinicStaff(clinic_id=clinic.id, user_id=sup_u.id),
        ClinicStaff(clinic_id=clinic.id, user_id=est_u.id, is_intern=True, internship_supervisor_id=sup_u.id,
                    can_manage_clients=True, can_manage_animals=True, can_manage_schedule=True),
        ClinicStaff(clinic_id=clinic.id, user_id=col_u.id),
    ])
    db.session.commit()
    return SimpleNamespace(clinic=clinic, sup=sup_u, sup_vet=sup, est=est_u, est_vet=est, col=col_u)


def _by_key(user, clinic):
    return {item.key: item for item in access_report(user, clinic)}


def test_estagiaria_supervisionada_atua_como_veterinaria(app, equipe):
    with app.test_request_context():
        report = _by_key(equipe.est, equipe.clinic)
    for key in ("atender", "clinico", "animais", "internacao", "internacao_prescrever", "orcamentos", "vacinacao_pmo"):
        assert report[key].allowed, key
    assert "Dr. Supervisor" in report["clinico"].detail
    assert not report["estoque"].allowed
    assert "Estoque" in report["estoque"].detail
    assert not report["equipe"].allowed
    assert not report["fiscal"].allowed


def test_marcar_estoque_libera_no_quadro(app, equipe):
    staff = ClinicStaff.query.filter_by(user_id=equipe.est.id).one()
    staff.can_manage_inventory = True
    db.session.commit()
    with app.test_request_context():
        assert _by_key(equipe.est, equipe.clinic)["estoque"].allowed


def test_supervisor_vencido_aparece_como_motivo(app, equipe):
    _membership(equipe.sup_vet, active=False)
    db.session.commit()
    with app.test_request_context():
        report = _by_key(equipe.est, equipe.clinic)
    assert not report["clinico"].allowed
    assert "assinatura do supervisor" in report["clinico"].detail


def test_estagiaria_sem_supervisor_aparece_como_motivo(app, equipe):
    equipe.est_vet.supervisor_id = None
    ClinicStaff.query.filter_by(user_id=equipe.est.id).one().internship_supervisor_id = None
    db.session.commit()
    with app.test_request_context():
        report = _by_key(equipe.est, equipe.clinic)
    assert not report["clinico"].allowed
    assert "sem supervisor" in report["clinico"].detail


def test_dono_tem_tudo_e_colaborador_nao_pratica_ato_clinico(app, equipe):
    with app.test_request_context():
        dono = _by_key(equipe.sup, equipe.clinic)
        colaborador = _by_key(equipe.col, equipe.clinic)
    assert all(item.allowed for key, item in dono.items() if key != "vacinacao_pmo")
    assert colaborador["atender"].allowed
    assert not colaborador["clinico"].allowed
    assert not colaborador["animais"].allowed


def test_relatorio_nao_grava_auditoria_de_negacao(app, equipe):
    from authz import _DENY_EVENTS_WINDOW

    before = len(_DENY_EVENTS_WINDOW)
    with app.test_request_context():
        access_report(equipe.col, equipe.clinic)
    assert len(_DENY_EVENTS_WINDOW) == before


def test_script_de_auditoria_lista_so_estagiarios(app, equipe):
    with app.test_request_context():
        linhas = linhas_relatorio(equipe.clinic, so_estagiarios=True)
    texto = "\n".join(linhas)
    assert "Laiane (user" in texto
    assert "Colaborador" not in texto
    assert "[NAO] Estoque" in texto
    assert "@" not in texto  # nada de e-mail na saída


def _login(client, user):
    g.pop("_login_user", None)
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


def test_quadro_aparece_para_o_dono_e_nao_para_a_equipe(client, equipe):
    _login(client, equipe.sup)
    html = client.get(f"/clinica/{equipe.clinic.id}").get_data(as_text=True)
    assert f'data-team-access="{equipe.est.id}"' in html
    assert "O que consegue fazer hoje" in html

    _login(client, equipe.col)
    response = client.get(f"/clinica/{equipe.clinic.id}")
    assert "O que consegue fazer hoje" not in response.get_data(as_text=True)
