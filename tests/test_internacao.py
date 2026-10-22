"""Contrato hospitalar: horários, histórico, execução e isolamento por clínica.

Todos os dados são simulados e usam o SQLite em memória da fixture ``app``.
As repetições de checagem provam a proteção contra retry e tela desatualizada;
não substituem um teste de concorrência com PostgreSQL em homologação.
"""

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import re
from types import SimpleNamespace

import pytest
from flask import g
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Animal, ClinicStaff, Clinica, Consulta, User, Veterinario
from models.internacao import (
    Internacao,
    InternacaoEvolucao,
    InternacaoOcorrencia,
    InternacaoPrescricao,
    InternacaoRegistro,
)
from services import internacao as hospital
from time_utils import normalize_to_utc


NOW = datetime(2026, 10, 22, 15, tzinfo=timezone.utc)
JSON_HEADERS = {"Accept": "application/json"}


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@pytest.fixture
def ward(app, monkeypatch):
    monkeypatch.setattr(hospital, "utcnow", lambda: NOW)
    monkeypatch.setattr("blueprints.internacao.utcnow", lambda: NOW)
    clinic = Clinica(nome="Clínica Norte")
    other_clinic = Clinica(nome="Clínica Sul")
    tutor = User(name="Tutor", email="internacao-tutor@test.local", password_hash="x")
    vet = User(name="Dra. Ana", email="internacao-vet@test.local", worker="veterinario", password_hash="x")
    worker = User(name="Bruno Plantonista", email="internacao-worker@test.local", worker="colaborador", password_hash="x")
    outsider = User(name="Veterinário externo", email="internacao-other@test.local", worker="veterinario", password_hash="x")
    intern = User(name="Estagiária", email="internacao-intern@test.local", worker="estagiario", role="estagiario", password_hash="x")
    db.session.add_all([clinic, other_clinic, tutor, vet, worker, outsider, intern])
    db.session.flush()
    vet.clinica_id = clinic.id
    worker.clinica_id = clinic.id
    intern.clinica_id = clinic.id
    outsider.clinica_id = other_clinic.id
    db.session.add_all([
        Veterinario(user_id=vet.id, crmv="SP-111", clinica_id=clinic.id),
        Veterinario(user_id=outsider.id, crmv="SP-222", clinica_id=other_clinic.id),
        Veterinario(user_id=intern.id, habilitacao="estagiario", clinica_id=clinic.id),
        ClinicStaff(clinic_id=clinic.id, user_id=vet.id),
        ClinicStaff(clinic_id=clinic.id, user_id=worker.id),
        ClinicStaff(clinic_id=clinic.id, user_id=intern.id, is_intern=True),
        ClinicStaff(clinic_id=other_clinic.id, user_id=outsider.id),
    ])
    animal = Animal(name="Luna", owner=tutor, clinica=clinic)
    other_animal = Animal(name="Rex externo", owner=tutor, clinica=other_clinic)
    db.session.add_all([animal, other_animal])
    db.session.flush()
    consultation = Consulta(animal_id=animal.id, created_by=vet.id, clinica_id=clinic.id)
    db.session.add(consultation)
    db.session.commit()
    return SimpleNamespace(
        clinic=clinic, other_clinic=other_clinic, tutor=tutor, vet=vet,
        worker=worker, outsider=outsider, intern=intern, animal=animal,
        other_animal=other_animal, consultation=consultation,
    )


def _admit(ward):
    admission = hospital.criar_internacao(ward.clinic.id, ward.animal, ward.vet, {
        "motivo": "Observação clínica simulada",
        "iniciada_em": NOW - timedelta(hours=6),
        "consulta_id": ward.consultation.id,
        "leito": "A-01",
        "responsavel_id": ward.vet.id,
        "alergias": "Desconhecidas",
    })
    db.session.commit()
    return admission


def _prescription_data(**changes):
    data = {
        "medicamento": "Medicamento de demonstração",
        "dose": "1 mL",
        "via": "Oral",
        "modo": "intervalo",
        "intervalo_horas": 8,
        "inicio_em": NOW - timedelta(hours=1),
        "fim_em": NOW + timedelta(hours=23),
        "instrucoes": "Dados fictícios para homologação; sem indicação terapêutica.",
    }
    data.update(changes)
    return data


def _prescribe(ward, admission=None, **changes):
    admission = admission or _admit(ward)
    prescription = hospital.prescrever(admission, ward.vet, _prescription_data(**changes))
    db.session.commit()
    return admission, prescription


def _doses(prescription):
    return InternacaoOcorrencia.query.filter_by(prescricao_id=prescription.id).order_by(InternacaoOcorrencia.prevista_para).all()


def _login(client, user):
    g.pop("_login_user", None)
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


def _form_inputs(html, action):
    class FormParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.selected = False
            self.values = None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "form":
                self.selected = attrs.get("action") == action
                if self.selected:
                    self.values = {}
            elif tag == "input" and self.selected and attrs.get("name"):
                self.values[attrs["name"]] = attrs.get("value", "")

        def handle_endtag(self, tag):
            if tag == "form":
                self.selected = False

    parser = FormParser()
    parser.feed(html)
    assert parser.values is not None, f"Formulário {action} não encontrado"
    return parser.values


def test_intervalo_cruza_meia_noite_sem_deslocar_horarios(ward):
    schedule = hospital.prever_horarios(_prescription_data(
        inicio_em="2026-10-22T22:00:00-03:00",
        fim_em="2026-10-23T22:00:00-03:00",
    ))
    assert [_utc(value) for value in schedule] == [
        datetime(2026, 10, 23, 1, tzinfo=timezone.utc),
        datetime(2026, 10, 23, 9, tzinfo=timezone.utc),
        datetime(2026, 10, 23, 17, tzinfo=timezone.utc),
    ]


def test_horarios_fixos_preservam_zona_local_e_fim_exclusivo(ward):
    schedule = hospital.prever_horarios(_prescription_data(
        modo="fixos", horarios_fixos=["08:00", "20:00"],
        inicio_em="2026-10-22T19:00:00-03:00",
        fim_em="2026-10-23T20:00:00-03:00",
    ))
    assert [_utc(value) for value in schedule] == [
        datetime(2026, 10, 22, 23, tzinfo=timezone.utc),
        datetime(2026, 10, 23, 11, tzinfo=timezone.utc),
    ]


def test_dose_unica_e_prn_nao_geram_agenda_ficticia(ward):
    assert len(hospital.prever_horarios(_prescription_data(modo="unica"))) == 1
    assert hospital.prever_horarios(_prescription_data(
        modo="prn", indicacao_prn="Conforme avaliação do veterinário",
        intervalo_minimo_horas=6, max_doses_24h=2,
    )) == []


def test_agenda_longa_nao_trunca_silenciosamente(ward):
    with pytest.raises(hospital.InternacaoError):
        hospital.prever_horarios(_prescription_data(fim_em=NOW + timedelta(days=40)))


def test_admissao_repetida_nao_duplica_internacao_ativa(ward):
    admission = _admit(ward)
    try:
        repeated = hospital.criar_internacao(ward.clinic.id, ward.animal, ward.vet, {
            "motivo": "Reenvio", "iniciada_em": NOW,
        })
    except hospital.InternacaoConflict:
        db.session.rollback()
    else:
        assert repeated.id == admission.id
    assert Internacao.query.filter_by(animal_id=ward.animal.id, status="ativa").count() == 1


def test_banco_impede_duas_admissoes_ativas_mesmo_sem_precheck(ward):
    original = _admit(ward)
    duplicate = Internacao(
        clinica_id=ward.clinic.id, animal_id=ward.animal.id,
        criado_por_id=ward.vet.id, responsavel_id=ward.vet.id,
        motivo="Segunda admissão concorrente", status="ativa", iniciada_em=NOW,
    )
    db.session.add(duplicate)
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()
    assert Internacao.query.one().id == original.id


def test_administracao_grava_autor_hora_servidor_e_preserva_agenda(ward):
    _, prescription = _prescribe(ward)
    doses = _doses(prescription)
    planned = [_utc(dose.prevista_para) for dose in doses]
    record = hospital.registrar_administracao(doses[0], ward.worker, {"idempotency_key": "dose-primeiro-envio"})
    db.session.commit()
    assert record.autor_id == ward.worker.id
    assert _utc(record.registrada_em) == NOW
    assert _utc(record.executada_em) == NOW
    assert _utc(doses[0].prevista_para) == NOW - timedelta(hours=1)
    assert [_utc(dose.prevista_para) for dose in _doses(prescription)] == planned


def test_retry_idempotente_e_segunda_checagem_nao_duplicam_execucao(ward):
    _, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    data = {"idempotency_key": "retry-conexao-001"}
    first = hospital.registrar_administracao(dose, ward.worker, data)
    db.session.commit()
    retry = hospital.registrar_administracao(dose, ward.worker, data)
    assert retry.id == first.id
    with pytest.raises(hospital.InternacaoConflict):
        hospital.registrar_administracao(dose, ward.vet, {"idempotency_key": "outro-funcionario"})
    assert InternacaoRegistro.query.filter_by(ocorrencia_id=dose.id).count() == 1


def test_omissao_exige_motivo_sem_apagar_horario_previsto(ward):
    _, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    with pytest.raises(hospital.InternacaoError):
        hospital.omitir_ocorrencia(dose, ward.worker, {})
    record = hospital.omitir_ocorrencia(dose, ward.worker, {"motivo": "Paciente em avaliação"})
    db.session.commit()
    assert record.resultado == "omitida"
    assert record.autor_id == ward.worker.id
    assert _utc(dose.prevista_para) == NOW - timedelta(hours=1)


def test_retificacao_preserva_registro_original_e_exige_motivo(ward):
    _, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    original = hospital.registrar_administracao(dose, ward.worker, {})
    db.session.commit()
    original_id = original.id
    original_time = _utc(original.executada_em)
    with pytest.raises(hospital.InternacaoError):
        hospital.retificar_registro(original, ward.vet, {"resultado": "omitida"})
    correction = hospital.retificar_registro(original, ward.vet, {
        "resultado": "omitida", "motivo": "Checagem lançada no paciente errado",
    })
    db.session.commit()
    db.session.expire_all()
    retained = db.session.get(InternacaoRegistro, original_id)
    assert retained.resultado == "administrada"
    assert _utc(retained.executada_em) == original_time
    assert retained.autor_id == ward.worker.id
    assert correction.retifica_id == original_id
    assert correction.autor_id == ward.vet.id
    assert correction.resultado == "omitida"
    assert InternacaoRegistro.query.filter_by(ocorrencia_id=dose.id).count() == 2


def test_revisao_preserva_dose_feita_e_cancela_futuras(ward):
    admission, original = _prescribe(ward)
    doses = _doses(original)
    record = hospital.registrar_administracao(doses[0], ward.worker, {})
    db.session.commit()
    revision = hospital.revisar_prescricao(original, ward.vet, _prescription_data(
        dose="2 mL", inicio_em=NOW, motivo="Reavaliação clínica simulada",
    ))
    db.session.commit()
    assert revision.id != original.id
    assert revision.internacao_id == admission.id
    assert db.session.get(InternacaoRegistro, record.id).resultado == "administrada"
    assert doses[0].status == "administrada"
    assert all(dose.status == "cancelada" for dose in doses[1:])
    assert original.dose == "1 mL"
    assert revision.dose == "2 mL"
    with pytest.raises(hospital.InternacaoError):
        hospital.registrar_administracao(doses[1], ward.worker, {})


def test_suspensao_impede_checagem_por_tela_antiga(ward):
    _, prescription = _prescribe(ward)
    dose = _doses(prescription)[1]
    hospital.suspender_prescricao(prescription, ward.vet, "Reavaliação")
    db.session.commit()
    with pytest.raises(hospital.InternacaoError):
        hospital.registrar_administracao(dose, ward.worker, {})
    assert InternacaoRegistro.query.filter_by(ocorrencia_id=dose.id).count() == 0


def test_suspensao_posterior_preserva_lancamento_legitimo_anterior(ward):
    _, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    hospital.suspender_prescricao(prescription, ward.vet, "Tratamento suspenso após reavaliação")
    db.session.commit()
    record = hospital.registrar_administracao(dose, ward.vet, {
        "executada_em": NOW - timedelta(minutes=30),
        "motivo": "Administração anterior à suspensão, lançada depois",
    })
    db.session.commit()
    assert record.resultado == "administrada"
    assert _utc(record.executada_em) < _utc(prescription.suspensa_em)


def test_revisao_futura_mantem_versao_anterior_executavel_ate_corte(ward, monkeypatch):
    _, original = _prescribe(ward)
    doses = _doses(original)
    hospital.revisar_prescricao(original, ward.vet, _prescription_data(
        inicio_em=NOW + timedelta(hours=10), dose="2 mL", motivo="Mudança com início futuro",
    ))
    db.session.commit()
    assert doses[1].status == "pendente"
    assert doses[2].status == "cancelada"
    record = hospital.registrar_administracao(doses[0], ward.worker, {})
    db.session.commit()
    assert record.resultado == "administrada"
    monkeypatch.setattr(hospital, "utcnow", lambda: NOW + timedelta(hours=11))
    with pytest.raises(hospital.InternacaoError):
        hospital.registrar_administracao(doses[1], ward.worker, {})


def test_antecipacao_exige_justificativa_mantendo_horario_previsto(ward):
    _, prescription = _prescribe(ward)
    dose = _doses(prescription)[1]
    with pytest.raises(hospital.InternacaoError):
        hospital.registrar_administracao(dose, ward.worker, {})
    record = hospital.registrar_administracao(dose, ward.worker, {"motivo": "Antecipação confirmada para teste"})
    db.session.commit()
    assert _utc(record.executada_em) == NOW
    assert _utc(dose.prevista_para) == NOW + timedelta(hours=7)


def test_fim_da_prescricao_bloqueia_execucao_atual_mas_preserva_registro_historico(ward, monkeypatch):
    _, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    monkeypatch.setattr(hospital, "utcnow", lambda: NOW + timedelta(hours=24))
    with pytest.raises(hospital.InternacaoError):
        hospital.registrar_administracao(dose, ward.worker, {})
    record = hospital.registrar_administracao(dose, ward.worker, {
        "executada_em": NOW, "motivo": "Registro tardio de execução dentro da vigência",
    })
    db.session.commit()
    assert _utc(record.executada_em) < _utc(prescription.fim_em)
    assert _utc(record.registrada_em) > _utc(prescription.fim_em)


def test_prn_limita_intervalo_e_quantidade_sem_criar_doses(ward, monkeypatch):
    _, prescription = _prescribe(ward, modo="prn", indicacao_prn="Avaliação clínica",
        intervalo_minimo_horas=6, max_doses_24h=2)
    assert _doses(prescription) == []
    first = hospital.registrar_prn(prescription, ward.worker, {"idempotency_key": "prn-1"})
    db.session.commit()
    assert hospital.registrar_prn(prescription, ward.worker, {"idempotency_key": "prn-1"}).id == first.id
    monkeypatch.setattr(hospital, "utcnow", lambda: NOW + timedelta(hours=1))
    with pytest.raises(hospital.InternacaoError):
        hospital.registrar_prn(prescription, ward.worker, {"idempotency_key": "prn-muito-cedo"})
    monkeypatch.setattr(hospital, "utcnow", lambda: NOW + timedelta(hours=6))
    hospital.registrar_prn(prescription, ward.worker, {"idempotency_key": "prn-2"})
    db.session.commit()
    monkeypatch.setattr(hospital, "utcnow", lambda: NOW + timedelta(hours=12))
    with pytest.raises(hospital.InternacaoError):
        hospital.registrar_prn(prescription, ward.worker, {"idempotency_key": "prn-terceira"})
    assert InternacaoRegistro.query.filter_by(prescricao_id=prescription.id).count() == 2


def test_revisao_prn_nao_zera_intervalo_da_ultima_administracao(ward, monkeypatch):
    _, original = _prescribe(ward, modo="prn", indicacao_prn="Avaliação clínica",
        intervalo_minimo_horas=6, max_doses_24h=2)
    hospital.registrar_prn(original, ward.worker, {})
    db.session.commit()
    revised = hospital.revisar_prescricao(original, ward.vet, _prescription_data(
        modo="prn", inicio_em=NOW + timedelta(minutes=5), indicacao_prn="Avaliação clínica",
        intervalo_minimo_horas=6, max_doses_24h=2, motivo="Atualização das instruções",
    ))
    db.session.commit()
    monkeypatch.setattr(hospital, "utcnow", lambda: NOW + timedelta(minutes=10))
    with pytest.raises(hospital.InternacaoError):
        hospital.registrar_prn(revised, ward.worker, {})
    assert InternacaoRegistro.query.count() == 1


def test_registro_tardio_distingue_execucao_de_lancamento(ward):
    _, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    executed = NOW - timedelta(minutes=30)
    with pytest.raises(hospital.InternacaoError):
        hospital.registrar_administracao(dose, ward.worker, {"executada_em": executed})
    record = hospital.registrar_administracao(dose, ward.worker, {
        "executada_em": executed, "motivo": "Registro após atendimento ao paciente",
    })
    db.session.commit()
    assert _utc(record.executada_em) == executed
    assert _utc(record.registrada_em) == NOW


@pytest.mark.parametrize("executed", [NOW + timedelta(minutes=1), NOW - timedelta(days=1)])
def test_registro_tardio_rejeita_futuro_e_antes_da_admissao(ward, executed):
    _, prescription = _prescribe(ward)
    with pytest.raises(hospital.InternacaoError):
        hospital.registrar_administracao(_doses(prescription)[0], ward.worker, {
            "executada_em": executed, "motivo": "Horário inválido para teste",
        })
    assert InternacaoRegistro.query.count() == 0


def test_alta_cancela_futuras_mas_aceita_historico_anterior_autorizado(ward, monkeypatch):
    admission, prescription = _prescribe(ward)
    doses = _doses(prescription)
    hospital.dar_alta(admission, ward.vet, {"resumo_alta": "Alta simulada após reavaliação"})
    db.session.commit()
    assert _utc(admission.encerrada_em) == NOW
    assert all(dose.status == "cancelada" for dose in doses[1:])
    monkeypatch.setattr(hospital, "utcnow", lambda: NOW + timedelta(hours=1))
    with pytest.raises(hospital.InternacaoError):
        hospital.registrar_administracao(doses[1], ward.vet, {})
    retrospective = hospital.registrar_administracao(doses[0], ward.vet, {
        "executada_em": NOW - timedelta(minutes=30),
        "motivo": "Conciliação de registro anterior à alta",
    })
    db.session.commit()
    assert _utc(retrospective.executada_em) < _utc(admission.encerrada_em)
    assert _utc(retrospective.registrada_em) > _utc(admission.encerrada_em)


@pytest.mark.parametrize("identity", ["tutor", "outsider", "intern"])
@pytest.mark.parametrize("resource", ["detail", "print", "animal"])
def test_prontuario_interno_nao_e_visivel_a_tutor_ou_outra_clinica(client, ward, identity, resource):
    admission = _admit(ward)
    paths = {
        "detail": f"/internacao/{admission.id}",
        "print": f"/internacao/{admission.id}/imprimir",
        "animal": f"/internacao/animal/{ward.animal.id}",
    }
    _login(client, getattr(ward, identity))
    response = client.get(paths[resource], headers=JSON_HEADERS)
    assert response.status_code in (403, 404)
    assert "Observação clínica simulada" not in response.get_data(as_text=True)


@pytest.mark.parametrize("identity", ["tutor", "outsider", "intern"])
def test_mutacoes_nao_aceitam_usuario_sem_acesso_a_clinica(client, ward, identity):
    admission, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    _login(client, getattr(ward, identity))
    paths_and_payloads = [
        (f"/internacao/{admission.id}/prescricoes", {"medicamento": "Invasão"}),
        (f"/internacao/{admission.id}/prescricoes/previa", {}),
        (f"/internacao/prescricoes/{prescription.id}/suspender", {"motivo": "Invasão"}),
        (f"/internacao/prescricoes/{prescription.id}/revisar", {}),
        (f"/internacao/prescricoes/{prescription.id}/registrar", {}),
        (f"/internacao/doses/{dose.id}/registrar", {"status": "administrada"}),
        (f"/internacao/{admission.id}/evolucoes", {"texto": "Invasão"}),
        (f"/internacao/{admission.id}/alta", {"resumo_alta": "Invasão"}),
    ]
    for path, data in paths_and_payloads:
        response = client.post(path, json=data, headers=JSON_HEADERS)
        assert response.status_code in (403, 404), (path, response.status_code)
    assert InternacaoRegistro.query.count() == 0
    assert InternacaoEvolucao.query.count() == 0
    assert InternacaoPrescricao.query.count() == 1
    assert admission.status == "ativa"


def test_plantonista_registra_mas_nao_prescreve_ou_da_alta(client, ward):
    admission, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    _login(client, ward.worker)
    assert client.get(f"/internacao/{admission.id}", headers=JSON_HEADERS).status_code == 200
    response = client.post(f"/internacao/doses/{dose.id}/registrar", json={
        "status": "administrada", "idempotency_key": "http-worker-001",
        "autor_id": ward.vet.id, "registrada_em": "2020-01-01T00:00:00Z",
    }, headers=JSON_HEADERS)
    assert response.status_code in (200, 201)
    record = InternacaoRegistro.query.one()
    assert record.autor_id == ward.worker.id
    assert _utc(record.registrada_em) == NOW
    for path in [f"/internacao/{admission.id}/prescricoes", f"/internacao/{admission.id}/alta"]:
        response = client.post(path, json={"resumo_alta": "Sem permissão"}, headers=JSON_HEADERS)
        assert response.status_code in (403, 404)
    assert admission.status == "ativa"


@pytest.mark.parametrize("identity", ["tutor", "outsider", "intern", "worker"])
def test_retificacao_exige_veterinario_autorizado_sem_modificar_original(client, ward, identity):
    _, prescription = _prescribe(ward)
    original = hospital.registrar_administracao(_doses(prescription)[0], ward.worker, {})
    db.session.commit()
    _login(client, getattr(ward, identity))
    response = client.post(f"/internacao/registros/{original.id}/retificar", json={
        "resultado": "pendente", "motivo": "Tentativa sem permissão",
    }, headers=JSON_HEADERS)
    assert response.status_code in (403, 404)
    assert InternacaoRegistro.query.count() == 1
    assert original.resultado == "administrada"


def test_troca_da_clinica_do_animal_nao_transfere_prontuario_hospitalar(client, ward):
    admission = _admit(ward)
    ward.animal.clinica_id = ward.other_clinic.id
    db.session.commit()
    _login(client, ward.outsider)
    assert client.get(f"/internacao/{admission.id}", headers=JSON_HEADERS).status_code in (403, 404)
    _login(client, ward.vet)
    assert client.get(f"/internacao/{admission.id}", headers=JSON_HEADERS).status_code == 200


def test_vet_nao_admite_animal_de_outra_clinica_manipulando_id(client, ward):
    _login(client, ward.vet)
    response = client.post("/internacao/nova", json={
        "animal_id": ward.other_animal.id, "clinica_id": ward.clinic.id,
        "motivo": "Não permitido", "responsavel_id": ward.vet.id,
    }, headers=JSON_HEADERS)
    assert response.status_code in (400, 403, 404)
    assert Internacao.query.count() == 0


def test_admite_animal_compartilhado_pela_consulta_da_clinica_correta(client, ward):
    consultation = Consulta(animal_id=ward.other_animal.id, clinica_id=ward.clinic.id, created_by=ward.vet.id)
    db.session.add(consultation)
    db.session.commit()
    _login(client, ward.vet)
    response = client.post("/internacao/nova", json={
        "animal_id": ward.other_animal.id, "clinica_id": ward.clinic.id,
        "consulta_id": consultation.id, "responsavel_id": ward.vet.id,
        "motivo": "Atendimento compartilhado na clínica Norte",
    }, headers=JSON_HEADERS)
    assert response.status_code == 201, response.get_data(as_text=True)
    admission = Internacao.query.one()
    assert admission.animal_id == ward.other_animal.id
    assert admission.clinica_id == ward.clinic.id
    assert ward.other_animal.clinica_id == ward.other_clinic.id
    _login(client, ward.outsider)
    assert client.get(f"/internacao/{admission.id}", headers=JSON_HEADERS).status_code in (403, 404)


def test_alta_entre_precheck_e_lock_nao_libera_registro_historico_para_staff(client, ward, monkeypatch):
    admission, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    lock = hospital._lock_internacao

    def close_before_lock_returns(*args, **kwargs):
        episode = lock(*args, **kwargs)
        episode.status = "alta"
        episode.encerrada_em = NOW
        db.session.flush()
        return episode

    monkeypatch.setattr(hospital, "_lock_internacao", close_before_lock_returns)
    _login(client, ward.worker)
    response = client.post(f"/internacao/doses/{dose.id}/registrar", json={
        "executada_em": (NOW - timedelta(minutes=30)).isoformat(),
        "motivo": "Pedido iniciado antes de alta concorrente",
    }, headers=JSON_HEADERS)
    assert response.status_code in (400, 403, 409)
    assert InternacaoRegistro.query.count() == 0


def test_jornada_http_da_consulta_ao_registro_plantao_e_alta(client, ward):
    _login(client, ward.vet)
    entry = client.get(f"/internacao/animal/{ward.animal.id}?consulta_id={ward.consultation.id}")
    assert entry.status_code == 302
    assert "/internacao/nova" in entry.location
    created = client.post("/internacao/nova", json={
        "animal_id": ward.animal.id, "consulta_id": ward.consultation.id,
        "clinica_id": ward.clinic.id, "responsavel_id": ward.vet.id,
        "motivo": "Jornada integrada simulada", "iniciada_em": (NOW - timedelta(hours=6)).isoformat(),
    }, headers=JSON_HEADERS)
    assert created.status_code == 201
    episode_id = created.get_json()["id"]
    data = _prescription_data(inicio_em=(NOW - timedelta(hours=1)).isoformat(), fim_em=(NOW + timedelta(hours=23)).isoformat())
    preview = client.post(f"/internacao/{episode_id}/prescricoes/previa", json=data, headers=JSON_HEADERS)
    assert preview.status_code == 200
    assert preview.get_json()["total"] == 3
    prescribed = client.post(f"/internacao/{episode_id}/prescricoes", json=data, headers=JSON_HEADERS)
    assert prescribed.status_code == 201
    prescription = db.session.get(InternacaoPrescricao, prescribed.get_json()["id"])
    dose = _doses(prescription)[0]
    _login(client, ward.worker)
    checked = client.post(f"/internacao/doses/{dose.id}/registrar", json={
        "idempotency_key": "journey-dose-1",
    }, headers=JSON_HEADERS)
    assert checked.status_code == 200
    handover = client.post(f"/internacao/{episode_id}/evolucoes", json={
        "tipo": "plantao", "texto": "Paciente acompanhado. Revisar pendências no próximo horário.",
        "pendencias": "Próxima dose conforme mapa",
    }, headers=JSON_HEADERS)
    assert handover.status_code == 201
    assert InternacaoEvolucao.query.one().autor_id == ward.worker.id
    _login(client, ward.vet)
    discharged = client.post(f"/internacao/{episode_id}/alta", json={
        "resumo_alta": "Jornada de homologação concluída",
    }, headers=JSON_HEADERS)
    assert discharged.status_code == 200
    episode = db.session.get(Internacao, episode_id)
    assert episode.status == "alta"
    assert episode.consulta_id == ward.consultation.id
    assert InternacaoRegistro.query.one().autor_id == ward.worker.id
    assert all(dose.status == "cancelada" for dose in _doses(prescription)[1:])


def test_impressao_mostra_paciente_programacao_e_autoria_em_a4(client, ward):
    admission, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    hospital.registrar_administracao(dose, ward.worker, {})
    db.session.commit()
    _login(client, ward.vet)
    response = client.get(f"/internacao/{admission.id}/imprimir")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Luna" in html
    assert "Clínica Norte" in html
    assert "Medicamento de demonstração" in html
    assert "Bruno Plantonista" in html
    assert "css/internacao.css" in html
    stylesheet = client.get("/static/css/internacao.css")
    assert stylesheet.status_code == 200
    css = stylesheet.get_data(as_text=True)
    assert "A4" in css
    assert "@page" in css
    assert "Previsto" in html or "previsto" in html
    assert "Realizado" in html or "realizado" in html or "Registrado" in html


def test_impressao_inclui_retificacao_posterior_a_alta_no_historico_do_periodo(client, ward, monkeypatch):
    admission, prescription = _prescribe(ward)
    original = hospital.registrar_administracao(_doses(prescription)[0], ward.worker, {
        "executada_em": NOW - timedelta(minutes=30), "motivo": "Administração antes da alta",
    })
    db.session.commit()
    hospital.dar_alta(admission, ward.vet, {"resumo_alta": "Alta para teste do histórico"})
    db.session.commit()
    monkeypatch.setattr(hospital, "utcnow", lambda: NOW + timedelta(hours=1))
    hospital.retificar_registro(original, ward.vet, {
        "resultado": "pendente", "executada_em": NOW - timedelta(minutes=30),
        "motivo": "Retificação de conciliação após a alta",
    })
    db.session.commit()
    _login(client, ward.vet)
    response = client.get(f"/internacao/{admission.id}/imprimir?tipo=prontuario")
    assert response.status_code == 200
    assert "Retificação de conciliação após a alta" in response.get_data(as_text=True)


def test_paginas_html_de_admissao_ficha_e_painel_renderizam(client, ward):
    admission, _ = _prescribe(ward)
    _login(client, ward.vet)
    for path in ["/internacao", f"/internacao/nova?animal_id={ward.animal.id}", f"/internacao/{admission.id}"]:
        response = client.get(path)
        assert response.status_code == 200, (path, response.get_data(as_text=True))
        assert "Luna" in response.get_data(as_text=True)


def test_formulario_sugere_inicio_valido_apos_admissao_com_segundos(client, ward, monkeypatch):
    admitted_at = NOW.replace(second=37)
    monkeypatch.setattr(hospital, "utcnow", lambda: admitted_at)
    monkeypatch.setattr("blueprints.internacao.utcnow", lambda: admitted_at)
    admission = hospital.criar_internacao(ward.clinic.id, ward.animal, ward.vet, {
        "motivo": "Admissão recém-confirmada", "responsavel_id": ward.vet.id,
    })
    db.session.commit()
    _login(client, ward.vet)
    response = client.get(f"/internacao/{admission.id}")
    assert response.status_code == 200
    values = _form_inputs(response.get_data(as_text=True), f"/internacao/{admission.id}/prescricoes")
    suggested = normalize_to_utc(values["inicio_em"])
    assert suggested >= _utc(admission.iniciada_em)
    assert suggested - _utc(admission.iniciada_em) <= timedelta(minutes=1)
    prescribed = client.post(f"/internacao/{admission.id}/prescricoes", json=_prescription_data(
        inicio_em=values["inicio_em"], fim_em=(suggested + timedelta(hours=24)).isoformat(),
    ), headers=JSON_HEADERS)
    assert prescribed.status_code == 201, prescribed.get_data(as_text=True)


def test_impressao_de_prescricao_futura_recem_publicada_informa_programada(client, ward):
    admission, prescription = _prescribe(ward, inicio_em=NOW + timedelta(hours=1))
    _login(client, ward.vet)
    response = client.get(f"/internacao/{admission.id}/imprimir?tipo=prescricao")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert prescription.medicamento in html
    assert "Programada — conferir início" in html
    assert "Nenhuma prescrição vigente ou programada" not in html


def test_impressao_antes_do_corte_distingue_anterior_vigente_de_revisao_programada(client, ward):
    admission, original = _prescribe(ward)
    hospital.revisar_prescricao(original, ward.vet, _prescription_data(
        inicio_em=NOW + timedelta(hours=2), dose="2 mL", motivo="Revisão com início futuro",
    ))
    db.session.commit()
    _login(client, ward.vet)
    response = client.get(f"/internacao/{admission.id}/imprimir?tipo=prescricao")
    assert response.status_code == 200
    articles = re.findall(r"<article\b[^>]*>(.*?)</article>", response.get_data(as_text=True), flags=re.S)
    assert any("1 mL" in article and "Vigente" in article for article in articles)
    assert any("2 mL" in article and "Programada — conferir início" in article for article in articles)


@pytest.mark.parametrize("action", ["prescrever", "revisar"])
@pytest.mark.parametrize("status", [400, 409])
def test_erro_html_de_prescricao_preserva_campos_preenchidos(client, ward, monkeypatch, action, status):
    admission, original = _prescribe(ward)
    path = (f"/internacao/{admission.id}/prescricoes" if action == "prescrever"
            else f"/internacao/prescricoes/{original.id}/revisar")
    _login(client, ward.vet)
    data = _prescription_data(
        medicamento="Medicamento com dados preservados", dose="0,75 mL", via="Via conferida",
        inicio_em="2026-10-22T12:01", fim_em="2026-10-23T12:01",
        intervalo_horas="0", motivo="Revisão de homologação",
    )
    if status == 409:
        data["intervalo_horas"] = "8"

        def concurrent_change(*_args, **_kwargs):
            raise hospital.InternacaoConflict("Registro alterado durante a revisão")

        monkeypatch.setattr(hospital, "prescrever" if action == "prescrever" else "revisar_prescricao", concurrent_change)
    response = client.post(path, data=data)
    assert response.status_code == status
    values = _form_inputs(response.get_data(as_text=True), path)
    for name in ["medicamento", "dose", "via", "inicio_em", "fim_em", "intervalo_horas"]:
        assert values[name] == data[name], name
    assert InternacaoPrescricao.query.count() == 1
    assert original.dose == "1 mL"


def test_revisao_da_versao_futura_nao_antecipa_para_periodo_da_predecessora(ward):
    _, original = _prescribe(ward)
    future = hospital.revisar_prescricao(original, ward.vet, _prescription_data(
        inicio_em=NOW + timedelta(hours=10), motivo="Primeira revisão futura",
    ))
    db.session.commit()
    with pytest.raises(hospital.InternacaoError):
        hospital.revisar_prescricao(future, ward.vet, _prescription_data(
            inicio_em=NOW + timedelta(hours=5), motivo="Não deve sobrepor a predecessora",
        ))
    db.session.rollback()
    assert InternacaoPrescricao.query.count() == 2
    assert _utc(original.suspensa_em) == NOW + timedelta(hours=10)


def test_retificar_para_pendente_antes_de_revisao_futura_permite_rechecagem(ward):
    _, original = _prescribe(ward)
    dose = _doses(original)[0]
    first_record = hospital.registrar_administracao(dose, ward.worker, {})
    db.session.commit()
    hospital.revisar_prescricao(original, ward.vet, _prescription_data(
        inicio_em=NOW + timedelta(hours=10), motivo="Nova versão no próximo plantão",
    ))
    db.session.commit()
    correction = hospital.retificar_registro(first_record, ward.vet, {
        "resultado": "pendente", "motivo": "Checagem anterior incorreta, dose ainda pendente",
    })
    db.session.commit()
    assert dose.status == "pendente"
    rechecked = hospital.registrar_administracao(dose, ward.worker, {})
    db.session.commit()
    assert rechecked.id != first_record.id
    assert rechecked.resultado == "administrada"
    assert correction.retifica_id == first_record.id
    assert db.session.get(InternacaoRegistro, first_record.id).resultado == "administrada"
    assert InternacaoRegistro.query.filter_by(ocorrencia_id=dose.id).count() == 3


@pytest.mark.parametrize("invalid", [False, True])
def test_parametros_basicos_do_formulario_persistem_e_aparecem_no_impresso(client, ward, invalid):
    admission = _admit(ward)
    _login(client, ward.worker)
    data = {
        "tipo": "evolucao", "texto": "Parâmetros aferidos durante o plantão",
        "param_temperatura": "<script>" if invalid else "38,2",
        "param_fc": "110", "param_fr": "24", "param_peso": "8,5",
    }
    response = client.post(f"/internacao/{admission.id}/evolucoes", data=data)
    if invalid:
        assert response.status_code == 400
        assert InternacaoEvolucao.query.count() == 0
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.data, 'html.parser')
        assert soup.select_one('textarea[name="texto"]').text == data['texto']
        assert soup.select_one('input[name="param_temperatura"]')['value'] == '<script>'
        return
    assert response.status_code == 303
    note = InternacaoEvolucao.query.one()
    expected = {
        "Temperatura (°C)": "38.2", "Frequência cardíaca (bpm)": "110",
        "Frequência respiratória (irpm)": "24", "Peso (kg)": "8.5",
    }
    assert note.parametros == expected
    assert note.autor_id == ward.worker.id
    printed = client.get(f"/internacao/{admission.id}/imprimir?tipo=prontuario")
    assert printed.status_code == 200
    html = printed.get_data(as_text=True)
    for label, value in expected.items():
        assert label in html
        assert value in html


def test_detalhe_internacao_renderiza_abas_mutuamente_exclusivas(client, ward):
    admission, _ = _prescribe(ward)
    _login(client, ward.vet)
    response = client.get(f"/internacao/{admission.id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Barra de abas com suporte a tabs e acessibilidade
    assert 'id="internacaoTabs"' in html
    assert 'id="internacaoTabContent"' in html
    assert 'data-bs-toggle="tab"' in html

    # Todas as cinco abas presentes nos links
    expected_tabs = ["#medicacoes", "#prescricoes", "#evolucoes", "#historico", "#documentos"]
    for tab_id in expected_tabs:
        assert f'href="{tab_id}"' in html
        assert f'data-bs-target="{tab_id}"' in html

    # Todas as cinco seções estruturadas como tab-pane e tabpanel
    for pane_id in ["medicacoes", "prescricoes", "evolucoes", "historico", "documentos"]:
        assert f'id="{pane_id}"' in html
        assert f'class="tab-pane fade' in html or f'class="tab-pane fade show active' in html
        assert f'role="tabpanel"' in html

