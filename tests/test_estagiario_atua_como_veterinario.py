"""Estagiário supervisionado faz tudo o que o veterinário faz.

Decisão do dono da clínica (out/2026): o estagiário atua como veterinário e
todo documento que ele emite sai no nome e CRMV do supervisor. A autoria real
continua nos registros (``saved_by``, ``created_by``) para acompanhar o
desenvolvimento do estagiário. Os dois cadastros de estágio que convivem no
sistema são cobertos: habilitação "estagiário" (tela da clínica) e vínculo de
estágio (convite de estudante).
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from flask import g

from extensions import db
from helpers import (
    can_act_as_veterinarian, ensure_veterinarian_membership, pessoa_no_documento,
    veterinarian_denial_message,
)
from models import Animal, ClinicStaff, Clinica, Consulta, User, Veterinario
from models.consulta import BlocoPrescricao, Prescricao
from time_utils import utcnow

HTML = {"Accept": "text/html,application/xhtml+xml"}
JSON = {"Accept": "application/json"}


def _membership(vet, *, active=True):
    membership = ensure_veterinarian_membership(vet)
    db.session.flush()
    now = utcnow()
    membership.started_at = now - timedelta(days=90)
    membership.trial_ends_at = now + timedelta(days=60) if active else now - timedelta(days=30)
    membership.paid_until = None
    return membership


@pytest.fixture
def clinica(app):
    clinic = Clinica(nome="Clínica Escola")
    tutor = User(name="Tutora", email="tutora@estagio.local", worker="adotante")
    sup_u = User(name="Dr. Supervisor", email="sup@estagio.local", worker="veterinario")
    est_u = User(name="Laiane Estagiária", email="laiane@estagio.local", worker="veterinario")
    conta_u = User(name="Estudante Conta", email="conta@estagio.local", worker="estudante")
    col_u = User(name="Colaborador", email="col@estagio.local", worker="colaborador")
    for user in (tutor, sup_u, est_u, conta_u, col_u):
        user.set_password("x")
    db.session.add_all([clinic, tutor, sup_u, est_u, conta_u, col_u])
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
    _membership(est)
    now = utcnow()
    db.session.add_all([
        ClinicStaff(clinic_id=clinic.id, user_id=sup_u.id),
        ClinicStaff(clinic_id=clinic.id, user_id=est_u.id),
        ClinicStaff(clinic_id=clinic.id, user_id=col_u.id),
        ClinicStaff(clinic_id=clinic.id, user_id=conta_u.id, is_intern=True,
                    internship_started_at=now - timedelta(days=1), internship_supervisor_id=sup_u.id),
    ])
    animal = Animal(name="Thor", owner=tutor, clinica=clinic)
    db.session.add(animal)
    db.session.flush()
    consulta = Consulta(animal_id=animal.id, created_by=sup_u.id, clinica_id=clinic.id, status="in_progress")
    db.session.add(consulta)
    db.session.commit()
    return SimpleNamespace(clinic=clinic, tutor=tutor, sup=sup_u, sup_vet=sup, est=est_u, est_vet=est,
                           conta=conta_u, col=col_u, animal=animal, consulta=consulta)


def _login(client, user):
    g.pop("_login_user", None)
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


def _flashes(client):
    with client.session_transaction() as session:
        return [message for _category, message in session.get("_flashes", [])]


@pytest.mark.parametrize("perfil", ["est", "conta"])
def test_estagiario_atua_como_veterinario_nos_dois_cadastros(clinica, perfil):
    user = getattr(clinica, perfil)
    assert can_act_as_veterinarian(user)
    assert pessoa_no_documento(user).id == clinica.sup.id
    assert pessoa_no_documento(clinica.sup).id == clinica.sup.id


@pytest.mark.parametrize("perfil", ["est", "conta"])
def test_estagiario_edita_animal_e_consulta(client, clinica, perfil):
    _login(client, getattr(clinica, perfil))
    response = client.post(f"/update_animal/{clinica.animal.id}", data={"name": "Bidu", "sex": "Macho"}, headers=HTML)
    assert response.status_code in (302, 303)
    db.session.refresh(clinica.animal)
    assert clinica.animal.name == "Bidu"
    response = client.post(f"/update_consulta/{clinica.consulta.id}", data={"queixa_principal": "Vômito"}, headers=HTML)
    assert response.status_code in (200, 302, 303)
    assert not any("Apenas veterinários" in message for message in _flashes(client))


def test_estagiario_prescreve_e_receita_sai_no_nome_do_supervisor(client, clinica):
    _login(client, clinica.est)
    response = client.post(
        f"/consulta/{clinica.consulta.id}/bloco_prescricao",
        json={"prescricoes": [{"medicamento": "Amoxicilina", "dosagem": "1 comp", "frequencia": "12/12h", "duracao": "7 dias"}]},
        headers=JSON,
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    bloco = BlocoPrescricao.query.one()
    assert bloco.saved_by_id == clinica.est.id, "a autoria real fica registrada"

    html = client.get(f"/bloco_prescricao/{bloco.id}/imprimir", headers=HTML).get_data(as_text=True)
    assert "Dr. Supervisor" in html
    assert "65152" in html
    assert "Laiane" not in html, "o papel não mostra o estagiário"


def test_pdf_da_receita_emitida_por_estagiario_assina_o_supervisor(client, clinica):
    bloco = BlocoPrescricao(clinica_id=clinica.clinic.id, animal_id=clinica.animal.id, saved_by_id=clinica.est.id)
    db.session.add(bloco)
    db.session.flush()
    db.session.add(Prescricao(bloco_id=bloco.id, animal_id=clinica.animal.id, medicamento="Dipirona"))
    db.session.commit()
    _login(client, clinica.est)
    response = client.get(f"/bloco_prescricao/{bloco.id}/pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    from services.receita_pdf import _assinatura
    assinatura = _assinatura(clinica.est)
    assert assinatura.nome == "Dr. Supervisor" and assinatura.pode_assinar


def test_termo_emitido_por_estagiario_sai_no_nome_do_supervisor(client, clinica):
    _login(client, clinica.est)
    html = client.get(f"/animal/{clinica.animal.id}/termo/viagem", headers=HTML).get_data(as_text=True)
    assert "Dr. Supervisor" in html
    assert "Laiane" not in html


def test_estagiario_opera_agenda_da_clinica(client, clinica):
    from models.agenda import Appointment
    appointment = Appointment(animal_id=clinica.animal.id, tutor_id=clinica.tutor.id,
                              veterinario_id=clinica.sup_vet.id, clinica_id=clinica.clinic.id,
                              scheduled_at=utcnow() + timedelta(days=1))
    db.session.add(appointment)
    db.session.commit()
    _login(client, clinica.conta)
    assert client.get("/appointments/manage", headers=HTML).status_code == 200


def test_estagiario_sem_supervisor_habilitado_recebe_motivo(client, clinica):
    clinica.est_vet.supervisor_id = None
    db.session.commit()
    assert not can_act_as_veterinarian(clinica.est)
    _login(client, clinica.est)
    client.post(f"/update_animal/{clinica.animal.id}", data={"name": "X"}, headers=HTML)
    assert any("sem supervisor com CRMV" in message for message in _flashes(client))


def test_supervisor_vencido_bloqueia_estagiario_com_motivo(client, clinica):
    _membership(clinica.sup_vet, active=False)
    db.session.commit()
    assert not can_act_as_veterinarian(clinica.est)
    _login(client, clinica.est)
    client.post(f"/update_animal/{clinica.animal.id}", data={"name": "X"}, headers=HTML)
    assert any("assinatura do seu supervisor" in message for message in _flashes(client))


def test_veterinario_com_assinatura_vencida_ve_o_motivo_real(client, clinica):
    _membership(clinica.sup_vet, active=False)
    db.session.commit()
    message = veterinarian_denial_message("Apenas veterinários podem editar dados do animal.", clinica.sup)
    assert message.startswith("Sua assinatura do PetOrlândia venceu")
    _login(client, clinica.sup)
    response = client.get(f"/consulta/{clinica.animal.id}", headers=HTML)
    assert response.status_code in (302, 303)
    assert "/veterinario/assinatura" in response.headers["Location"]


def test_colaborador_so_edita_animal_com_permissao_animais(client, clinica):
    _login(client, clinica.col)
    client.post(f"/update_animal/{clinica.animal.id}", data={"name": "Bob"}, headers=HTML)
    db.session.refresh(clinica.animal)
    assert clinica.animal.name == "Thor"
    assert any("Apenas veterinários e estagiários supervisionados" in m for m in _flashes(client))
    staff = ClinicStaff.query.filter_by(user_id=clinica.col.id).one()
    staff.can_manage_animals = True
    db.session.commit()
    client.post(f"/update_animal/{clinica.animal.id}", data={"name": "Fred", "sex": "Macho"}, headers=HTML)
    db.session.refresh(clinica.animal)
    assert clinica.animal.name == "Fred"
    # A permissão "Animais" não vira ato clínico.
    response = client.post(f"/update_consulta/{clinica.consulta.id}", data={"queixa_principal": "x"}, headers=HTML)
    assert any("Apenas veterinários" in m for m in _flashes(client)) or response.status_code == 403


def _render_animal_form(app, clinica, user):
    from flask import render_template
    from flask_login import login_user

    with app.test_request_context("/consulta_qr"):
        login_user(user)
        from forms.pacientes import AnimalForm

        return render_template("partials/animal_form.html", animal=clinica.animal, form=AnimalForm(obj=clinica.animal),
                               species_list=[], breed_list=[], breed_map={})


def test_formulario_do_animal_so_oferece_salvar_a_quem_pode(app, clinica):
    html = _render_animal_form(app, clinica, clinica.col)
    assert "Somente leitura: o seu perfil não edita o cadastro do animal" in html
    assert "animal-save-btn" not in html
    assert "marcar_falecido" not in html
    html = _render_animal_form(app, clinica, clinica.est)
    assert "animal-save-btn" in html
    assert "marcar_falecido" in html


def test_rota_antiga_de_prescricao_grava_em_bloco(client, clinica):
    _login(client, clinica.sup)
    response = client.post(f"/consulta/{clinica.consulta.id}/prescricao", data={"medicamento": "Meloxicam"}, headers=HTML)
    assert response.status_code in (302, 303)
    prescricao = Prescricao.query.filter_by(medicamento="Meloxicam").one()
    assert prescricao.bloco_id and prescricao.animal_id == clinica.animal.id


def test_internacao_estagiario_prescreve_e_impressao_mostra_supervisor(client, clinica, monkeypatch):
    from services import internacao as hospital
    from services.internacao_access import pode_prescrever_internacao, pode_ser_responsavel_internacao

    assert pode_prescrever_internacao(clinica.est, clinica.clinic.id)
    assert not pode_ser_responsavel_internacao(clinica.est, clinica.clinic.id)
    assert pode_ser_responsavel_internacao(clinica.sup, clinica.clinic.id)
    episode = hospital.criar_internacao(clinica.clinic.id, clinica.animal, clinica.est, {
        "motivo": "Observação", "responsavel_id": clinica.sup.id,
        "iniciada_em": utcnow() - timedelta(hours=2),
    })
    hospital.prescrever(episode, clinica.est, {
        "medicamento": "Ondansetrona", "dose": "1 mL", "via": "IV", "modo": "intervalo", "intervalo_horas": 8,
        "inicio_em": utcnow() - timedelta(hours=1), "fim_em": utcnow() + timedelta(hours=20),
    })
    db.session.commit()
    _login(client, clinica.est)
    html = client.get(f"/internacao/{episode.id}/imprimir?tipo=prescricao", headers=HTML).get_data(as_text=True)
    assert "Prescritor:</strong> Dr. Supervisor" in html
    assert "CRMV 65152" in html
    nova = client.get(f"/internacao/nova?clinica_id={clinica.clinic.id}", headers=HTML).get_data(as_text=True)
    assert "Laiane Estagiária</option>" not in nova, "responsável técnico continua sendo quem tem CRMV"
