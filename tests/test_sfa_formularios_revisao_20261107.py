"""Instrumentos T0/T7/T30 ajustados ao documento de perguntas revisado em 07/11/2026."""
from datetime import date
from types import SimpleNamespace

import pytest

from services import sfa_service, sfa_workflow


def _schema(stage):
    return sfa_service.carregar_form_schema(stage)


def _campos(schema):
    return {field["key"]: field for section in schema["sections"] for field in section["fields"]}


def test_versao_anterior_fica_arquivada_com_os_campos_retirados():
    t0 = sfa_service.carregar_schema_historico_instrumento("sfa-2026-11-06", "t0")
    t30 = sfa_service.carregar_schema_historico_instrumento("sfa-2026-11-06", "t30")

    assert t0["instrument_version"] == "sfa-2026-11-06"
    assert "temperatura_medida" in _campos(t0)
    assert "data_retorno" in _campos(t30)


def test_resposta_da_versao_anterior_continua_lida_com_o_proprio_instrumento():
    schema = sfa_service.carregar_schema_para_payload("t0", {"_instrument_version": "sfa-2026-11-06"})

    assert schema["_readonly"] is True
    assert "temperatura_medida" in _campos(schema)


def test_exportacao_inclui_colunas_da_versao_anterior():
    chaves = {
        key
        for schema in sfa_service._schemas_exportacao_por_stage("t0")
        for key in _campos(schema)
    }
    assert {"temperatura_medida", "modo_entrevista"} <= chaves


@pytest.mark.parametrize("stage", ["t0", "t7", "t30"])
def test_registro_da_entrevista_abre_cada_formulario(stage):
    primeira = _schema(stage)["sections"][0]
    chaves = [field["key"] for field in primeira["fields"]]

    assert primeira["title"] == "Registro da entrevista"
    assert chaves[:3] == ["modo_entrevista", "entrevistador", "local_servico"]
    assert _campos(_schema(stage))["modo_entrevista"]["options"][:2] == ["Presencial", "Telefone"]
    assert ("momento_entrevista" in chaves) is (stage == "t0")


def test_t0_segue_a_ordem_de_blocos_do_documento():
    titulos = [section["title"] for section in _schema("t0")["sections"]]

    assert titulos == [
        "Registro da entrevista",
        "Participação e início dos sintomas",
        "Ambiente e deslocamento da pessoa",
        "Contato com animais",
        "Alimentos, água e produtos consumidos",
        "Outras pessoas com sintomas parecidos",
    ]


def test_t0_tem_as_opcoes_nao_sei_do_documento_e_sem_temperatura():
    campos = _campos(_schema("t0"))

    assert campos["data_inicio_sintomas_ignorada"]["options"] == ["Não sabe informar"]
    for chave in ("exposicao_alimentar_data_ignorada", "exposicao_alimentar_quantidades_ignoradas",
                  "outras_pessoas_quantidade_ignorada", "inicio_outros_ignorado"):
        assert campos[chave]["options"] == ["Não sei"], chave
    assert "temperatura_medida" not in campos
    assert "data_temperatura" not in campos
    assert "Não sei" not in campos["tipo_contato_animal"]["options"]
    assert "onde dormiu" in campos["exposicao_ambiental_detalhe"]["help_text"]


def test_t7_nao_pergunta_a_relacao_com_o_t0():
    schema = _schema("t7")
    campos = _campos(schema)

    assert [s["title"] for s in schema["sections"]][1:] == [
        "Evolução e atendimento",
        "Informação sobre o diagnóstico",
        "Impacto individual desde o início dos sintomas",
        "Informações coletivas",
    ]
    # A relação com o T0 é calculada pelo sistema (ver test_sfa_link_morador_20261109).
    assert "pista_coletiva_confirmada" not in campos
    assert campos["dias_incap_novos_sem_numero"]["options"] == ["Nenhum", "Não sei"]
    ajuda = campos["atendimento_detalhe"]["help_text"]
    assert "particulares ou fora de Orlândia" in ajuda
    assert "Hospital" not in ajuda  # sem nome de serviço específico como exemplo


def test_t30_usa_as_situacoes_do_documento():
    campos = _campos(_schema("t30"))
    opcoes = campos["impacto_periodo"]["options"]

    assert opcoes[:3] == [
        "Houve dias em que não consegui realizar minhas atividades habituais",
        "Minha família ou eu tivemos gastos",
        "Perdi renda ou deixei de ganhar dinheiro",
    ]
    assert campos["dias_incap_novos"]["visible_if"]["values"] == [opcoes[0]]
    # Gasto só Sim/Não, sem valor (decisão da equipe, 09/11/2026).
    assert "custo_outros" not in campos and "custo_outros_ignorado" not in campos
    assert campos["retornou_servico_saude"]["options"] == ["Sim", "Não"]
    assert "pista_coletiva_confirmada" not in campos
    for retirado in ("data_retorno", "retorno_sem_data", "impacto_item_desconhecido"):
        assert retirado not in campos


def test_t30_mostra_a_data_inicial_do_periodo_na_pergunta_8(monkeypatch):
    monkeypatch.setattr(sfa_service, "obter_payload_formulario", lambda paciente, stage: (None, {}))
    monkeypatch.setattr(sfa_workflow, "inicio_doenca", lambda paciente: (date(2026, 10, 20), "T0"))
    paciente = SimpleNamespace(resposta_t0=None, respostas_t7=[], respostas_t10=[], respostas_t30=[])

    filtrado = sfa_service.filtrar_form_schema_condicional(_schema("t30"), paciente, "t30")

    assert _campos(filtrado)["impacto_periodo"]["label"].startswith("8. Desde 20/10/2026,")


@pytest.mark.parametrize("versao", sorted(sfa_workflow.INTERVIEW_VERSIONS))
def test_as_duas_revisoes_de_novembro_usam_o_calendario_pela_entrevista(versao):
    payload = {"_instrument_version": versao, "respondent_role": "A própria pessoa",
               "situacao_participante": "Sim", "sintoma_novo_agravado": "Sim"}

    assert sfa_workflow.INTERVIEW_VERSIONS == {"sfa-2026-11-06", "sfa-2026-11-07", "sfa-2026-11-09", "sfa-2026-11-09b"}
    assert sfa_service.classificar_desfecho_primario_t30(payload) == "Sim"
    assert sfa_service.normalizar_payload_t0_exposicoes(payload) == payload
