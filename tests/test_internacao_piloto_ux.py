"""Fluxo do plantão piloto: checagem sem atrito, ronda no painel e telas enxutas.

Cobre os gargalos levantados no teste da equipe piloto (out/2026). Dados
fictícios; SQLite em memória da fixture ``app``.
"""
import re
from datetime import timedelta

import pytest
from sqlalchemy import event

from extensions import db
from models import Animal, ClinicStaff, User
from models.internacao import InternacaoOcorrencia, InternacaoRegistro
from services import internacao as hospital
try:
    from tests.test_internacao import (  # noqa: F401  (fixture reutilizada)
        JSON_HEADERS, NOW, _admit, _doses, _login, _prescribe, _prescription_data, _utc, ward,
    )
except ImportError:
    from test_internacao import (  # noqa: F401  (fixture reutilizada)
        JSON_HEADERS, NOW, _admit, _doses, _login, _prescribe, _prescription_data, _utc, ward,
    )


def _count_queries(app, call):
    statements = []

    def before(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", before)
    try:
        response = call()
    finally:
        event.remove(db.engine, "before_cursor_execute", before)
    return response, len(statements)


def _at(monkeypatch, moment):
    monkeypatch.setattr(hospital, "utcnow", lambda: moment)
    monkeypatch.setattr("blueprints.internacao.utcnow", lambda: moment)


# Gargalo 4 — janela de tolerância simétrica ---------------------------------

def test_antecipacao_dentro_da_janela_dispensa_justificativa(ward, monkeypatch):
    _, prescription = _prescribe(ward)
    dose = _doses(prescription)[1]  # prevista para NOW + 7 h
    _at(monkeypatch, _utc(dose.prevista_para) - timedelta(minutes=10))
    record = hospital.registrar_administracao(dose, ward.worker, {})
    assert record.resultado == "administrada"


def test_antecipacao_alem_da_janela_continua_exigindo_justificativa(ward, monkeypatch):
    _, prescription = _prescribe(ward)
    dose = _doses(prescription)[1]
    _at(monkeypatch, _utc(dose.prevista_para) - timedelta(minutes=61))
    with pytest.raises(hospital.InternacaoError, match="antes do horário"):
        hospital.registrar_administracao(dose, ward.worker, {})


def test_primeira_dose_pode_ser_antecipada_dentro_da_janela(client, ward):
    # Caso da equipe: prescrição começa às 18:00 e a dose é dada às 17:10.
    _, prescription = _prescribe(ward, inicio_em=NOW + timedelta(minutes=50))
    dose = _doses(prescription)[0]
    _login(client, ward.worker)
    response = client.post(f"/internacao/doses/{dose.id}/registrar", data={
        "resultado": "administrada", "motivo": "Tudo ok", "observacoes": "Tudo ok.",
    }, headers=JSON_HEADERS)
    assert response.status_code == 200, response.get_data(as_text=True)
    record = InternacaoRegistro.query.one()
    assert _utc(record.executada_em) == NOW and record.ocorrencia_id == dose.id
    # O registro antecipado continua retificável.
    hospital.retificar_registro(record, ward.vet, {"motivo": "Complemento da observação"})


def test_primeira_dose_antecipada_com_horario_real_informado(ward, monkeypatch):
    _, prescription = _prescribe(ward, inicio_em=NOW + timedelta(minutes=50))
    dose = _doses(prescription)[0]
    _at(monkeypatch, NOW + timedelta(minutes=5))
    record = hospital.registrar_administracao(dose, ward.worker, {
        "executada_em": NOW, "motivo": "Lançado logo após a administração",
    })
    assert _utc(record.executada_em) == NOW


def test_primeira_dose_alem_da_janela_continua_bloqueada_antes_do_inicio(ward):
    _, prescription = _prescribe(ward, inicio_em=NOW + timedelta(minutes=90))
    first, second = _doses(prescription)[:2]
    # 90 min antes do início: libera 60 min antes da primeira dose (13:30 em Brasília).
    with pytest.raises(hospital.InternacaoError, match="a partir de 22/10/2026 12:30"):
        hospital.registrar_administracao(first, ward.worker, {"motivo": "Antes do horário"})
    # Doses seguintes não abrem antes do início da prescrição.
    with pytest.raises(hospital.InternacaoError, match="a partir de 22/10/2026 13:30"):
        hospital.omitir_ocorrencia(second, ward.worker, {"motivo": "Jejum"})
    assert InternacaoRegistro.query.count() == 0


def test_atraso_alem_da_janela_exige_justificativa(ward, monkeypatch):
    _, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]  # prevista para NOW - 1 h
    _at(monkeypatch, _utc(dose.prevista_para) + timedelta(hours=4))
    with pytest.raises(hospital.InternacaoError, match="atraso"):
        hospital.registrar_administracao(dose, ward.worker, {})
    record = hospital.registrar_administracao(dose, ward.worker, {"motivo": "Paciente em exame de imagem"})
    assert record.motivo == "Paciente em exame de imagem"


def test_atraso_dentro_da_janela_nao_exige_justificativa(ward):
    _, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]  # 60 min de atraso em NOW
    assert hospital.registrar_administracao(dose, ward.worker, {}).resultado == "administrada"


def test_tolerancia_configuravel(app, ward, monkeypatch):
    app.config["INTERNACAO_TOLERANCIA_MINUTOS"] = 15
    try:
        _, prescription = _prescribe(ward)
        dose = _doses(prescription)[1]
        _at(monkeypatch, _utc(dose.prevista_para) - timedelta(minutes=20))
        with pytest.raises(hospital.InternacaoError, match="15 min"):
            hospital.registrar_administracao(dose, ward.worker, {})
    finally:
        app.config.pop("INTERNACAO_TOLERANCIA_MINUTOS", None)


# Gargalos 1 a 3 — checagem sem recarregar, retorno à dose e erro no formulário

def test_checagem_json_devolve_dados_para_atualizar_a_linha(client, ward):
    admission, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    _login(client, ward.worker)
    response = client.post(f"/internacao/doses/{dose.id}/registrar",
                           data={"resultado": "administrada", "idempotency_key": "linha-1"}, headers=JSON_HEADERS)
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body["ok"] and body["dose_id"] == dose.id
    assert body["resultado"] == "administrada"
    assert body["autor"] == ward.worker.name
    assert re.match(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", body["executada_em"])


def test_checagem_tradicional_volta_para_a_propria_dose(client, ward):
    admission, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    _login(client, ward.worker)
    response = client.post(f"/internacao/doses/{dose.id}/registrar", data={"resultado": "administrada"})
    assert response.status_code == 303
    assert response.headers["Location"].endswith(f"/internacao/{admission.id}#dose-{dose.id}")


def test_recusa_reabre_a_dose_com_texto_e_mensagem(client, ward):
    admission, prescription = _prescribe(ward)
    dose = _doses(prescription)[1]  # 7 h antes do previsto
    _login(client, ward.worker)
    response = client.post(f"/internacao/doses/{dose.id}/registrar", data={
        "resultado": "administrada", "observacoes": "Observação digitada", "idempotency_key": "chave-mantida",
    })
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert f'data-ih-focus="dose-{dose.id}"' in html
    row = re.search(rf'<tr id="dose-{dose.id}".*?</tr>', html, re.S).group(0)
    assert "data-ih-dose-details open" in row
    assert 'value="Observação digitada"' in row
    assert 'value="chave-mantida"' in row
    assert "ih-form-msg--erro" in row and "justificativa" in row
    assert InternacaoRegistro.query.count() == 0


def test_paginas_da_internacao_mantem_avisos_visiveis(client, ward):
    admission = _admit(ward)
    _login(client, ward.worker)
    for path in ("/internacao", f"/internacao/{admission.id}"):
        assert "data-keep-alerts" in client.get(path).get_data(as_text=True)


# Gargalos 5, 6 e 11 — ronda no painel, passagem de plantão e clínica lembrada

def test_painel_permite_checar_a_dose_na_ronda(client, ward):
    admission, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    _login(client, ward.worker)
    html = client.get("/internacao").get_data(as_text=True)
    assert f'action="/internacao/doses/{dose.id}/registrar"' in html
    assert 'name="voltar" value="painel"' in html
    response = client.post(f"/internacao/doses/{dose.id}/registrar",
                           data={"resultado": "administrada", "voltar": "painel"})
    assert response.status_code == 303
    assert f"/internacao?clinica_id={ward.clinic.id}" in response.headers["Location"]
    assert db.session.get(InternacaoOcorrencia, dose.id).status == "administrada"


def test_voltar_ao_painel_nao_aceita_destino_externo(client, ward):
    admission, prescription = _prescribe(ward)
    dose = _doses(prescription)[0]
    _login(client, ward.worker)
    response = client.post(f"/internacao/doses/{dose.id}/registrar",
                           data={"resultado": "administrada", "voltar": "https://exemplo.invalid"})
    assert response.headers["Location"].endswith(f"/internacao/{admission.id}#dose-{dose.id}")


def test_painel_mostra_passagem_de_plantao_e_filtra_atrasadas(client, ward):
    admission, prescription = _prescribe(ward)
    hospital.registrar_evolucao(admission, ward.worker, {
        "tipo": "plantao", "texto": "Noite sem intercorrências", "pendencias": "Coletar hemograma às 8h"})
    db.session.commit()
    _login(client, ward.worker)
    html = client.get("/internacao").get_data(as_text=True)
    assert "Passagem de plantão" in html and "Coletar hemograma às 8h" in html
    late = client.get("/internacao?doses=atrasadas").get_data(as_text=True)
    doses = _doses(prescription)
    assert f'id="dose-{doses[0].id}"' in late  # prevista há 1 h
    assert f'id="dose-{doses[1].id}"' not in late  # ainda no futuro


def test_painel_lembra_a_ultima_clinica_escolhida(client, ward):
    ward.worker.clinica_id = None
    db.session.add(ClinicStaff(clinic_id=ward.other_clinic.id, user_id=ward.worker.id))
    db.session.commit()
    _login(client, ward.worker)
    client.get(f"/internacao?clinica_id={ward.other_clinic.id}")
    html = client.get("/internacao").get_data(as_text=True)
    assert re.search(rf'<option value="{ward.other_clinic.id}" selected>', html)


def test_painel_abre_na_clinica_do_proprio_usuario(client, ward):
    # "Clínica Sul" vem depois em ordem alfabética; ainda assim é a do usuário.
    db.session.add(ClinicStaff(clinic_id=ward.other_clinic.id, user_id=ward.worker.id))
    ward.worker.clinica_id = ward.other_clinic.id
    db.session.commit()
    _login(client, ward.worker)
    html = client.get("/internacao").get_data(as_text=True)
    assert re.search(rf'<option value="{ward.other_clinic.id}" selected>', html)


# Gargalos 8 e 9 — telas enxutas e consultas agrupadas

def _ward_with_patients(ward, count):
    episodes = []
    for index in range(count):
        animal = Animal(name=f"Paciente {index}", owner=ward.tutor, clinica=ward.clinic)
        db.session.add(animal)
        db.session.flush()
        episode = hospital.criar_internacao(ward.clinic.id, animal, ward.vet, {
            "motivo": "Volume", "iniciada_em": NOW - timedelta(days=2), "responsavel_id": ward.vet.id})
        for hours in (4, 6, 8):
            hospital.prescrever(episode, ward.vet, _prescription_data(
                intervalo_horas=hours, inicio_em=NOW - timedelta(days=2), fim_em=NOW + timedelta(days=1)))
        episodes.append(episode)
    db.session.commit()
    return episodes


def test_consultas_do_painel_nao_crescem_com_o_numero_de_doses(app, client, ward):
    _ward_with_patients(ward, 2)
    _login(client, ward.worker)
    _, few = _count_queries(app, lambda: client.get("/internacao"))
    _ward_with_patients(ward, 6)
    _, many = _count_queries(app, lambda: client.get("/internacao"))
    assert many - few <= 2, (few, many)


def test_consultas_do_prontuario_nao_crescem_com_o_historico(app, client, ward):
    episode = _ward_with_patients(ward, 1)[0]
    _login(client, ward.vet)
    _, before = _count_queries(app, lambda: client.get(f"/internacao/{episode.id}"))
    for dose in InternacaoOcorrencia.query.filter(
            InternacaoOcorrencia.internacao_id == episode.id,
            InternacaoOcorrencia.prevista_para < NOW - timedelta(hours=1)).all():
        hospital.registrar_administracao(dose, ward.worker, {
            "executada_em": _utc(dose.prevista_para), "motivo": "Lançamento de volume"})
    db.session.commit()
    _, after = _count_queries(app, lambda: client.get(f"/internacao/{episode.id}"))
    assert after - before <= 3, (before, after)


def test_historico_mostra_24h_e_retificacao_sob_demanda(client, ward):
    admission, prescription = _prescribe(ward)
    doses = _doses(prescription)
    old = hospital.registrar_administracao(doses[0], ward.worker, {
        "executada_em": NOW - timedelta(minutes=50), "motivo": "Lançamento"})
    db.session.commit()
    # Um registro com mais de 24 h sai da tela padrão, mas não da impressão.
    db.session.execute(InternacaoRegistro.__table__.update().where(
        InternacaoRegistro.id == old.id).values(registrada_em=NOW - timedelta(days=2),
                                                 executada_em=NOW - timedelta(days=2)))
    db.session.commit()
    _login(client, ward.vet)
    html = client.get(f"/internacao/{admission.id}").get_data(as_text=True)
    assert f'id="registro-{old.id}"' not in html and "Ver todo o histórico" in html
    full = client.get(f"/internacao/{admission.id}?historico=todos").get_data(as_text=True)
    assert f'id="registro-{old.id}"' in full
    assert f'action="/internacao/registros/{old.id}/retificar"' not in full
    assert f"retificar={old.id}" in full
    opened = client.get(f"/internacao/{admission.id}?historico=todos&retificar={old.id}").get_data(as_text=True)
    assert f'action="/internacao/registros/{old.id}/retificar"' in opened
    printed = client.get(f"/internacao/{admission.id}/imprimir?tipo=prontuario&inicio=2026-10-01").get_data(as_text=True)
    assert f"#{old.id}" in printed


# Gargalo 7 — início em hora cheia, com atalhos ---------------------------------

def test_formulario_de_prescricao_oferece_atalhos(client, ward):
    admission = _admit(ward)
    _login(client, ward.vet)
    html = client.get(f"/internacao/{admission.id}").get_data(as_text=True)
    assert 'data-ih-duracao="24"' in html and 'data-ih-duracao="168"' in html
    assert ">Agora</button>" in html and ">Próxima hora cheia</button>" in html


def test_busca_de_medicamento_da_prescricao_consulta_o_catalogo(client, ward):
    from models import Medicamento

    db.session.add(Medicamento(nome="Dipirona sódica", principio_ativo="Dipirona",
                               classificacao="Analgésico", created_by=ward.vet.id))
    db.session.commit()
    admission = _admit(ward)
    _login(client, ward.vet)
    html = client.get(f"/internacao/{admission.id}").get_data(as_text=True)
    # Lista própria: <datalist> não aparece em navegadores de celular.
    assert "<datalist" not in html
    field = re.search(r"<input[^>]*data-ih-medicamento[^>]*>", html).group(0)
    assert 'role="combobox"' in field and 'aria-controls="ih-medicamentos-nova"' in field
    assert 'id="ih-medicamentos-nova" role="listbox"' in html
    url = re.search(r'data-search-url="([^"]+)"', field).group(1).replace("&amp;", "&")
    assert f"animal_id={admission.animal_id}" in url
    results = client.get(f"{url}&q=dipir", headers=JSON_HEADERS).get_json()
    assert any(item["nome"] == "Dipirona sódica" for item in results)


# Campos compactos: número + unidade para quantidade e intervalo -----------------

def _compact_form(**changes):
    data = _prescription_data(dose_valor="2", dose_unidade="comprimido", intervalo_valor="8",
                              intervalo_unidade="horas", inicio_em="2026-10-22T13:00",
                              fim_em="2026-10-23T13:00")
    del data["dose"], data["intervalo_horas"]
    data.update(changes)
    return data


@pytest.mark.parametrize("valor, unidade, outra, esperado", [
    ("2", "comprimido", "", "2 comprimidos"),
    ("1,5", "comprimido", "", "1,5 comprimido"),
    ("1/2", "comprimido", "", "1/2 comprimido"),
    ("0.50", "mL", "", "0,5 mL"),
    ("20", "gota", "", "20 gotas"),
    ("10", "g", "", "10 g"),
    ("2,5", "outra", "mL/kg/h", "2,5 mL/kg/h"),
    ("", "outra", "Conforme tabela anexa", "Conforme tabela anexa"),
])
def test_quantidade_compacta_vira_texto_da_dose(valor, unidade, outra, esperado):
    from blueprints.internacao import _dose_text

    assert _dose_text({"dose_valor": valor, "dose_unidade": unidade, "dose_unidade_outra": outra}) == esperado


@pytest.mark.parametrize("dados", [
    {"dose_valor": "2", "dose_unidade": ""},
    {"dose_valor": "", "dose_unidade": "mL"},
    {"dose_valor": "0", "dose_unidade": "mL"},
    {"dose_valor": "dois", "dose_unidade": "mL"},
    {"dose_valor": "1", "dose_unidade": "outra", "dose_unidade_outra": ""},
])
def test_quantidade_compacta_recusa_valores_invalidos(dados):
    from blueprints.internacao import _dose_text

    with pytest.raises(hospital.InternacaoError):
        _dose_text(dados)


@pytest.mark.parametrize("valor, unidade, horas", [
    ("8", "horas", "8"), ("1,5", "horas", "1.5"), ("30", "minutos", "0.5"),
    ("15", "minutos", "0.25"), ("2", "dias", "48"),
])
def test_intervalo_compacto_converte_para_horas(valor, unidade, horas):
    from blueprints.internacao import _interval_hours

    assert _interval_hours({"x_valor": valor, "x_unidade": unidade}, "x", "o intervalo") == horas


@pytest.mark.parametrize("valor, unidade", [
    ("20", "minutos"), ("7,5", "minutos"), ("0", "horas"), ("31", "dias"), ("8", "semanas"),
])
def test_intervalo_compacto_recusa_horarios_inexatos_ou_invalidos(valor, unidade):
    from blueprints.internacao import MAX_INTERVAL_HOURS, _interval_hours

    with pytest.raises(hospital.InternacaoError):
        _interval_hours({"x_valor": valor, "x_unidade": unidade}, "x", "o intervalo", MAX_INTERVAL_HOURS)


@pytest.mark.parametrize("texto, partes", [
    ("2 comprimidos", {"valor": "2", "unidade": "comprimido", "outra": ""}),
    ("0,5 mL", {"valor": "0,5", "unidade": "mL", "outra": ""}),
    ("1/2 comprimido", {"valor": "1/2", "unidade": "comprimido", "outra": ""}),
    ("2,5 mL/kg/h", {"valor": "2,5", "unidade": "outra", "outra": "mL/kg/h"}),
    ("Meia ampola", {"valor": "", "unidade": "outra", "outra": "Meia ampola"}),
    ("", {"valor": "", "unidade": "", "outra": ""}),
])
def test_dose_gravada_volta_separada_para_o_formulario(texto, partes):
    from blueprints.internacao import split_dose

    assert split_dose(texto) == partes


@pytest.mark.parametrize("horas, partes, exibido", [
    ("8.000", ("8", "horas"), "8 h"), ("0.5", ("30", "minutos"), "30 min"),
    ("48", ("2", "dias"), "2 dias"), ("24", ("1", "dias"), "1 dia"), ("1.5", ("1,5", "horas"), "1,5 h"),
])
def test_intervalo_gravado_volta_na_unidade_natural(horas, partes, exibido):
    from blueprints.internacao import format_interval, split_interval

    assert split_interval(horas) == partes
    assert format_interval(horas) == exibido


def test_prescricao_pelo_formulario_compacto_grava_dose_e_intervalo(client, ward):
    from models.internacao import InternacaoPrescricao

    admission = _admit(ward)
    _login(client, ward.vet)
    path = f"/internacao/{admission.id}/prescricoes"
    preview = client.post(f"{path}/previa", data=_compact_form(intervalo_valor="30", intervalo_unidade="minutos"),
                          headers=JSON_HEADERS)
    assert preview.status_code == 200 and preview.get_json()["total"] == 48
    response = client.post(path, data=_compact_form(
        apresentacao="500 mg comprimido", intervalo_valor="30", intervalo_unidade="minutos"))
    assert response.status_code == 303
    order = InternacaoPrescricao.query.one()
    assert order.dose == "2 comprimidos" and order.apresentacao == "500 mg comprimido"
    assert float(order.intervalo_horas) == 0.5
    html = client.get(f"/internacao/{admission.id}").get_data(as_text=True)
    assert "A cada 30 min" in html
    revision = re.search(rf'<form[^>]*action="/internacao/prescricoes/{order.id}/revisar".*?</form>', html, re.S).group(0)
    assert 'name="dose_valor" value="2"' in revision
    assert '<option value="comprimido" selected>' in revision
    assert 'name="intervalo_valor" value="30"' in revision
    assert '<option value="minutos" selected>' in revision


def test_prn_aceita_intervalo_minimo_em_dias(client, ward):
    from models.internacao import InternacaoPrescricao

    admission = _admit(ward)
    _login(client, ward.vet)
    data = _compact_form(modo="prn", indicacao_prn="Dor", intervalo_minimo_valor="1",
                         intervalo_minimo_unidade="dias", max_doses_24h="1")
    del data["intervalo_valor"], data["intervalo_unidade"]
    assert client.post(f"/internacao/{admission.id}/prescricoes", data=data).status_code == 303
    assert float(InternacaoPrescricao.query.one().intervalo_minimo_horas) == 24


def test_intervalo_em_minutos_inexato_explica_e_nao_grava(client, ward):
    from models.internacao import InternacaoPrescricao

    admission = _admit(ward)
    _login(client, ward.vet)
    response = client.post(f"/internacao/{admission.id}/prescricoes",
                           data=_compact_form(intervalo_valor="20", intervalo_unidade="minutos"),
                           headers=JSON_HEADERS)
    assert response.status_code == 400
    assert "múltiplos de 3" in response.get_json()["erro"]
    assert InternacaoPrescricao.query.count() == 0


def test_dose_mostra_apresentacao_no_painel_e_na_checagem(client, ward):
    _prescribe(ward, apresentacao="500 mg/mL gotas", dose="20 gotas")
    _login(client, ward.vet)
    html = client.get(f"/internacao?clinica_id={ward.clinic.id}").get_data(as_text=True)
    card = html[html.index("ih-dose-card__what"):]
    assert card.index("500 mg/mL gotas") < card.index("20 gotas")
    assert "(500 mg/mL gotas)" in html


# Gargalo 10 — busca na admissão --------------------------------------------

def test_admissao_busca_por_animal_ou_tutor_alem_da_lista(client, ward):
    tutor = User(name="Marta Responsável", email="marta@test.local", password_hash="x")
    db.session.add(tutor)
    for index in range(505):
        db.session.add(Animal(name=f"Animal {index:03d}", owner=ward.tutor, clinica=ward.clinic))
    late = Animal(name="Zeus", owner=tutor, clinica=ward.clinic)
    db.session.add(late)
    db.session.commit()
    _login(client, ward.vet)
    listing = client.get(f"/internacao/nova?clinica_id={ward.clinic.id}").get_data(as_text=True)
    assert "Use a busca para encontrar os demais" in listing and "Zeus" not in listing
    found = client.get(f"/internacao/nova?clinica_id={ward.clinic.id}&q=Marta").get_data(as_text=True)
    assert re.search(rf'<option value="{late.id}" selected>Zeus', found)


# Gargalo 12 — bloqueio explicado -------------------------------------------------

def test_auxiliar_recebe_explicacao_ao_tentar_ato_do_veterinario(client, ward):
    admission = _admit(ward)
    _login(client, ward.worker)
    response = client.post(f"/internacao/{admission.id}/alta", data={"resumo_alta": "x"})
    assert response.status_code == 403
    assert "Somente veterinário com CRMV" in response.get_data(as_text=True)
    as_json = client.post(f"/internacao/{admission.id}/prescricoes", json=_prescription_data(), headers=JSON_HEADERS)
    assert as_json.status_code == 403
    assert "Somente veterinário com CRMV" in as_json.get_json()["erro"]
    assert db.session.get(type(admission), admission.id).status == "ativa"
