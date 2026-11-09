"""Link do morador (09/11/2026): o sistema preenche o que antes a equipe tinha de lembrar."""
import json
from datetime import date
from types import SimpleNamespace

from werkzeug.datastructures import MultiDict

from services import sfa_service


def _campos(schema):
    return {field["key"]: field for section in schema["sections"] for field in section["fields"]}


def _resposta(payload):
    return SimpleNamespace(dados_json=json.dumps(payload, ensure_ascii=False), timestamp=None, id=1)


def _paciente(t0=None, t7=None):
    return SimpleNamespace(
        id_estudo="", ficha_sinan="", nome="", data_nascimento="", token_acesso="", contexto=None,
        _sinan_log=None, _sinan_dados={},
        resposta_t0=_resposta(t0) if t0 else None,
        respostas_t7=[_resposta(t7)] if t7 else [], respostas_t10=[], respostas_t30=[],
    )


def _descricao_coletiva(schema):
    return next(s["description"] for s in schema["sections"] if s["title"] == "Informações coletivas")


def test_versao_de_07_11_fica_arquivada_com_as_perguntas_retiradas():
    t0 = sfa_service.carregar_schema_historico_instrumento("sfa-2026-11-07", "t0")
    t7 = sfa_service.carregar_schema_historico_instrumento("sfa-2026-11-07", "t7")
    t30 = sfa_service.carregar_schema_historico_instrumento("sfa-2026-11-07", "t30")

    assert {"versao_tcle", "data_aceite"} <= set(_campos(t0))
    assert "pista_coletiva_confirmada" in _campos(t7)
    assert "pista_coletiva_confirmada" in _campos(t30)


def test_instrumento_atual_nao_pede_o_que_o_sistema_sabe():
    t0 = _campos(sfa_service.carregar_form_schema("t0"))
    assert "versao_tcle" not in t0 and "data_aceite" not in t0
    for stage in ("t7", "t30"):
        schema = sfa_service.carregar_form_schema(stage)
        assert "pista_coletiva_confirmada" not in _campos(schema)
        assert "pista_coletiva_descricao" not in _campos(schema)
        assert "Aplicar as perguntas" not in _descricao_coletiva(schema)
        texto = json.dumps(schema, ensure_ascii=False)
        assert '"source": "current", "key": "pista_coletiva_confirmada"' not in texto


def test_pistas_do_t0_e_do_t7_viram_frases_para_a_pessoa():
    t0 = {"outras_pessoas_com_sintomas": "Sim", "exposicao_animal_outros_doentes": ["Animais"],
          "vinculo_exposicao_suspeita": "  Água   do poço  "}
    t7 = {"novos_casos_semelhantes": "Sim", "nova_pista_exposicao": "Sim", "nova_pista_detalhe": "Queijo da feira",
          "pista_coletiva_confirmada": "Sim", "pista_coletiva_descricao": "repetida",
          "_pista_coletiva_automatica": True}

    assert sfa_service.pistas_coletivas_anteriores([t0, t7]) == [
        "outras pessoas tiveram febre ou sintomas parecidos",
        "outros animais ligados aos animais com que você teve contato também adoeceram",
        "suspeitava de “Água do poço”",
        "depois da primeira entrevista, soube de novas pessoas com sintomas parecidos",
        "surgiu uma nova informação: “Queijo da feira”",
    ]
    assert sfa_service.pistas_coletivas_anteriores([{"outras_pessoas_com_sintomas": "Não"}]) == []
    # T7 da versão de 07/11, com a pista registrada à mão pela equipe.
    manual = {"pista_coletiva_confirmada": "Sim", "pista_coletiva_descricao": "Surto na escola"}
    assert sfa_service.pistas_coletivas_anteriores([manual]) == ["a equipe registrou uma pista: “Surto na escola”"]


def test_t7_abre_o_bloco_coletivo_lembrando_o_que_a_pessoa_contou():
    base = sfa_service.carregar_form_schema("t7")
    com_pista = sfa_service.filtrar_form_schema_condicional(
        base, _paciente(t0={"exposicao_alimentar_outros_doentes": "Sim"}), "t7")
    sem_pista = sfa_service.filtrar_form_schema_condicional(
        base, _paciente(t0={"outras_pessoas_com_sintomas": "Não"}), "t7")

    assert _descricao_coletiva(com_pista) == (
        "Parte 2 — Informações coletivas. Na primeira entrevista, você contou que outras pessoas que "
        "consumiram o mesmo alimento, água ou produto também adoeceram. Agora queremos saber se surgiu "
        "alguma novidade."
    )
    assert _descricao_coletiva(sem_pista) == _descricao_coletiva(base)
    # As perguntas 17 e 18 seguem a pista do T0 sem pergunta intermediária: com pista
    # aparecem sempre; sem pista, só se a pessoa contar novos casos ou nova informação.
    assert "visible_if" not in _campos(com_pista)["fonte_ainda_ativa"]
    regra = json.dumps(_campos(sem_pista)["fonte_ainda_ativa"]["visible_if"])
    assert "novos_casos_semelhantes" in regra and "pista_coletiva_confirmada" not in regra


def test_link_do_morador_tira_registro_da_entrevista_e_grava_o_modo():
    paciente = _paciente(t0={"outras_pessoas_com_sintomas": "Sim"})
    schema = sfa_service.adaptar_schema_link_morador(
        sfa_service.filtrar_form_schema_condicional(sfa_service.carregar_form_schema("t7"), paciente, "t7"))
    campos = _campos(schema)

    assert schema["sections"][0]["title"] != "Registro da entrevista"
    assert not sfa_service.CAMPOS_REGISTRO_ENTREVISTA & set(campos)
    assert campos["observacoes_entrevistador"]["label"] == "Observações"

    dados, erros = sfa_service.coletar_resposta_t7_nativa(
        schema, MultiDict({"respondent_role": "A própria pessoa", "modo_entrevista": "Telefone"}), paciente)

    assert erros == {}
    assert dados["modo_entrevista"] == sfa_service.MODO_ENTREVISTA_LINK
    assert dados["pista_coletiva_confirmada"] == "Sim"
    assert dados["pista_coletiva_descricao"] == "outras pessoas tiveram febre ou sintomas parecidos"


def test_formulario_sem_modo_link_nao_inventa_o_modo_da_entrevista():
    schema = sfa_service.carregar_form_schema("t7")
    dados, _ = sfa_service.coletar_resposta_t7_nativa(
        schema, MultiDict({"respondent_role": "A própria pessoa", "modo_entrevista": "Telefone"}), _paciente())

    assert dados["modo_entrevista"] == "Telefone"
    assert dados["pista_coletiva_confirmada"] == "Não"


def test_t0_registra_versao_e_data_do_tcle_sozinho(monkeypatch):
    monkeypatch.setattr("services.sfa_workflow.hoje_local", lambda: date(2026, 11, 9))
    schema = sfa_service.adaptar_schema_link_morador(sfa_service.carregar_form_schema("t0"))
    form = MultiDict({"respondent_role": "A própria pessoa", "participante_faixa_etaria": "18 anos ou mais",
                      "aceite_tcle": sfa_service.T0_CONSENT_ACCEPTED})

    dados, erros = sfa_service.coletar_resposta_t0_nativa(schema, form, _paciente())

    assert "aceite_tcle" not in erros
    assert dados["versao_tcle"] == sfa_service.TCLE_VERSAO_ATUAL
    assert dados["data_aceite"] == "09/11/2026"
    assert _campos(schema)["aceite_tcle"]["label"] == "2. Termo de Consentimento (TCLE)"
