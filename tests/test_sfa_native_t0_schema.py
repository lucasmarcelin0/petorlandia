import json
from pathlib import Path
from types import SimpleNamespace

from werkzeug.datastructures import MultiDict

from services import sfa_service
from services.sfa_service import (
    carregar_t10_form_schema,
    carregar_t30_form_schema,
    carregar_t0_form_schema,
    coletar_resposta_t0_nativa,
    construir_valores_iniciais_t0,
    construir_valores_iniciais_t10,
    construir_valores_iniciais_t30,
    salvar_t0_form_schema,
    serializar_t0_form_schema,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMPORTED_KEYS = {"cpf", "nome", "ficha_sinan", "data_nascimento", "endereco"}


def _paciente_fake():
    return SimpleNamespace(
        token_acesso="token-abc",
        id_estudo="SFA-900",
        ficha_sinan="3032976",
        nome="Maria Teste",
        data_nascimento="01/01/2000",
        endereco="Rua Exemplo, 123",
        bairro="Centro",
        resposta_t0=None,
        respostas_t10=[],
        respostas_t30=[],
    )


def _fields_by_key(schema):
    return {
        field["key"]: field
        for section in schema["sections"]
        for field in section["fields"]
    }


def _valid_t0_form_data(*, include_consent=True):
    items = [
        ("respondent_role", "A propria pessoa"),
        ("outras_pessoas_com_sintomas", "Nao"),
        ("exposicao_ambiental", "Nenhuma exposicao ambiental"),
        ("exposicao_animal", "Nenhum contato animal relevante"),
        ("exposicao_alimentar", "Nenhuma dessas"),
        ("diagnostico_medico", "Nao"),
        ("sinais_alerta_atuais", "Nenhum destes sinais agora"),
        ("dias_incap", "2"),
        ("houve_gasto", "Nao"),
        ("ausencia_familiar", "Nao"),
    ]
    if include_consent:
        items.append(("aceite_tcle", sfa_service.T0_CONSENT_ACCEPTED))
    return MultiDict(items)


def test_carregar_t0_form_schema_eh_instrumento_coletivo_essencial():
    schema = carregar_t0_form_schema()
    fields = _fields_by_key(schema)

    assert schema["title"] == "T0 - Exposicoes coletivas e prevencao"
    assert schema["instrument_version"] == "collective-v2"
    assert IMPORTED_KEYS.isdisjoint(fields)
    assert "vacinas_12_meses" not in fields
    assert {
        "respondent_role",
        "aceite_tcle",
        "outras_pessoas_com_sintomas",
        "exposicao_ambiental",
        "exposicao_animal",
        "exposicao_alimentar",
        "diagnostico_medico",
        "custo_total",
    } <= fields.keys()
    assert "Caes" in fields["exposicao_animal"]["options"]
    assert "Gatos" in fields["exposicao_animal"]["options"]
    assert "Caes ou gatos" not in fields["exposicao_animal"]["options"]


def test_validar_t0_form_schema_bloqueia_opcao_animal_redundante():
    schema = json.loads(json.dumps(carregar_t0_form_schema()))
    animal_field = _fields_by_key(schema)["exposicao_animal"]
    animal_field["options"].append("Caes ou gatos domesticos")

    errors = sfa_service.validar_t0_form_schema(schema)

    assert any("use Caes e Gatos como opcoes separadas" in error for error in errors)


def test_normalizar_payload_t0_exposicoes_converte_legado_para_categorias_atuais():
    payload = {
        "contato_animais": [
            "Caes ou gatos domesticos",
            "Gatos filhotes ou limpeza de fezes de gato",
            "Nenhum contato com animais",
        ],
        "consumo_recente": ["Agua nao tratada (poco, rio, mina)"],
        "atividades_recentes": ["Lazer em area rural/chacara"],
    }

    normalized = sfa_service.normalizar_payload_t0_exposicoes(payload)

    assert normalized["exposicao_animal"] == ["Caes", "Gatos"]
    assert normalized["contato_animais"] == ["Caes", "Gatos"]
    assert normalized["exposicao_alimentar"] == ["Agua nao tratada"]
    assert normalized["exposicao_ambiental"] == ["Area rural/chacara"]


def test_carregar_t10_t30_form_schemas_tem_campos_coletivos_e_custo_totalizado():
    schema_t10 = carregar_t10_form_schema()
    schema_t30 = carregar_t30_form_schema()
    fields_t10 = _fields_by_key(schema_t10)
    fields_t30 = _fields_by_key(schema_t30)

    assert schema_t10["title"] == "T10 - Novas pistas e permanencia da fonte"
    assert schema_t30["title"] == "T30 - Encerramento do risco coletivo"
    assert schema_t10["instrument_version"] == "collective-v2"
    assert schema_t30["instrument_version"] == "collective-v2"
    assert IMPORTED_KEYS.isdisjoint(fields_t10)
    assert IMPORTED_KEYS.isdisjoint(fields_t30)
    assert {
        "classificacao_melhora",
        "novos_casos_semelhantes",
        "nova_pista_exposicao",
    } <= fields_t10.keys()
    assert {
        "estado_saude_final",
        "nova_informacao_fonte",
        "orientacao_ou_acao_percebida",
    } <= fields_t30.keys()
    assert "custo_outros" in fields_t10
    assert "custo_outros" in fields_t30
    for removed_key in ("custo_remedios", "custo_consultas", "custo_transporte"):
        assert removed_key not in fields_t10
        assert removed_key not in fields_t30


def test_diagnostico_medico_permanece_nos_followups_como_atualizacao():
    paciente = _paciente_fake()
    paciente.resposta_t0 = SimpleNamespace(
        dados_json=json.dumps(
            {
                "_submitted_stage": "t0",
                "diagnostico_medico": "Sim",
                "diagnostico_medico_qual": "Dengue",
            }
        )
    )

    schema_t10 = sfa_service.filtrar_form_schema_condicional(
        carregar_t10_form_schema(), paciente, "t10"
    )
    schema_t30 = sfa_service.filtrar_form_schema_condicional(
        carregar_t30_form_schema(), paciente, "t30"
    )
    fields_t10 = _fields_by_key(schema_t10)
    fields_t30 = _fields_by_key(schema_t30)

    assert "diagnostico_medico" in fields_t10
    assert "diagnostico_medico_qual" in fields_t10
    assert fields_t10["diagnostico_medico_qual_outro"]["visible_if"] == {
        "source": "current",
        "key": "diagnostico_medico_qual",
        "operator": "equals",
        "value": "Outro",
    }
    assert "Depois do T0" in fields_t10["diagnostico_medico"]["label"]
    assert "diagnostico_medico" in fields_t30
    assert "diagnostico_medico_qual" in fields_t30
    assert fields_t30["diagnostico_medico_qual_outro"]["visible_if"] == {
        "source": "current",
        "key": "diagnostico_medico_qual",
        "operator": "equals",
        "value": "Outro",
    }
    assert "Depois do ultimo contato" in fields_t30["diagnostico_medico"]["label"]


def test_diagnostico_outro_exige_descricao_por_escrito_no_t0():
    form_data = _valid_t0_form_data()
    form_data.setlist("diagnostico_medico", ["Sim"])
    form_data.setlist("diagnostico_medico_status", ["Confirmacao"])
    form_data.setlist("diagnostico_medico_qual", ["Outro"])

    dados, errors = coletar_resposta_t0_nativa(
        carregar_t0_form_schema(), form_data, _paciente_fake()
    )
    assert errors["diagnostico_medico_qual_outro"] == "Campo obrigatorio."
    assert dados["diagnostico_medico_qual_outro"] == ""

    form_data.setlist("diagnostico_medico_qual_outro", ["Leptospirose"])
    dados, errors = coletar_resposta_t0_nativa(
        carregar_t0_form_schema(), form_data, _paciente_fake()
    )
    assert errors == {}
    assert dados["diagnostico_medico_qual"] == "Outro"
    assert dados["diagnostico_medico_qual_outro"] == "Leptospirose"


def test_valores_iniciais_nao_reexibem_dados_importados():
    paciente = _paciente_fake()
    paciente.resposta_t0 = SimpleNamespace(
        dados_json=json.dumps({"cpf": "12345678900", "nome": "Nome informado no T0"})
    )

    values_t0 = construir_valores_iniciais_t0(paciente, carregar_t0_form_schema())
    values_t10 = construir_valores_iniciais_t10(paciente, carregar_t10_form_schema())
    values_t30 = construir_valores_iniciais_t30(paciente, carregar_t30_form_schema())

    assert IMPORTED_KEYS.isdisjoint(values_t0)
    assert IMPORTED_KEYS.isdisjoint(values_t10)
    assert IMPORTED_KEYS.isdisjoint(values_t30)


def test_coletar_resposta_t0_nativa_salva_contexto_e_versao_sem_campos_visiveis():
    dados, errors = coletar_resposta_t0_nativa(
        carregar_t0_form_schema(), _valid_t0_form_data(), _paciente_fake()
    )

    assert errors == {}
    assert dados["token_acesso"] == "token-abc"
    assert dados["id_estudo"] == "SFA-900"
    assert dados["ficha_sinan"] == "3032976"
    assert dados["nome"] == "Maria Teste"
    assert dados["data_nascimento"] == "01/01/2000"
    assert dados["_imported_context"]["ficha_sinan"] == "3032976"
    assert dados["_instrument_version"] == "collective-v2"
    assert dados["_submitted_stage"] == "t0"
    assert dados["aceite_tcle"] == [sfa_service.T0_CONSENT_ACCEPTED]


def test_coletar_resposta_t0_nativa_exige_aceite_do_tcle():
    _dados, errors = coletar_resposta_t0_nativa(
        carregar_t0_form_schema(),
        _valid_t0_form_data(include_consent=False),
        _paciente_fake(),
    )

    assert errors["aceite_tcle"] == "Voce precisa aceitar o TCLE para enviar o formulario."


def test_tampering_em_campo_oculto_e_descartado():
    form_data = _valid_t0_form_data()
    form_data["custo_total"] = "99999"
    form_data["diagnostico_medico_qual"] = "Valor inventado"
    form_data["diagnostico_medico_status"] = "Confirmacao"

    dados, errors = coletar_resposta_t0_nativa(
        carregar_t0_form_schema(), form_data, _paciente_fake()
    )

    assert errors == {}
    assert dados["custo_total"] == ""
    assert dados["diagnostico_medico_qual"] == ""
    assert dados["diagnostico_medico_status"] == ""


def test_tampering_com_opcao_invalida_e_rejeitado():
    form_data = _valid_t0_form_data()
    form_data["respondent_role"] = "Perfil inexistente"

    _dados, errors = coletar_resposta_t0_nativa(
        carregar_t0_form_schema(), form_data, _paciente_fake()
    )

    assert errors["respondent_role"] == "Opcao de resposta invalida."


def test_tampering_com_numero_acima_do_maximo_e_rejeitado():
    form_data = _valid_t0_form_data()
    form_data["dias_incap"] = "61"

    _dados, errors = coletar_resposta_t0_nativa(
        carregar_t0_form_schema(), form_data, _paciente_fake()
    )

    assert errors["dias_incap"] == "O valor maximo e 60."


def test_tampering_checkbox_nenhuma_com_exposicao_positiva_e_rejeitado():
    form_data = _valid_t0_form_data()
    form_data.setlist(
        "exposicao_animal", ["Nenhum contato animal relevante", "Carrapato"]
    )

    _dados, errors = coletar_resposta_t0_nativa(
        carregar_t0_form_schema(), form_data, _paciente_fake()
    )

    assert errors["exposicao_animal"] == (
        "Escolha 'nenhuma' ou as exposicoes informadas, nao ambas."
    )


def test_prior_abre_ou_mantem_condicional_fechada_no_t10():
    paciente_com_pista = _paciente_fake()
    paciente_com_pista.resposta_t0 = SimpleNamespace(
        dados_json=json.dumps(
            {
                "_submitted_stage": "t0",
                "exposicao_animal_outros_doentes": "Sim",
            }
        )
    )
    paciente_sem_pista = _paciente_fake()
    paciente_sem_pista.resposta_t0 = SimpleNamespace(
        dados_json=json.dumps(
            {
                "_submitted_stage": "t0",
                "outras_pessoas_com_sintomas": "Nao",
                "exposicao_ambiental": ["Nenhuma exposicao ambiental"],
                "exposicao_animal": ["Nenhum contato animal relevante"],
                "exposicao_alimentar": ["Nenhuma dessas"],
                "outra_exposicao_suspeita": "",
            }
        )
    )

    aberto = _fields_by_key(
        sfa_service.filtrar_form_schema_condicional(
            carregar_t10_form_schema(), paciente_com_pista, "t10"
        )
    )["fonte_ainda_ativa"]
    fechado_ate_gatilho_atual = _fields_by_key(
        sfa_service.filtrar_form_schema_condicional(
            carregar_t10_form_schema(), paciente_sem_pista, "t10"
        )
    )["fonte_ainda_ativa"]

    assert "visible_if" not in aberto
    assert fechado_ate_gatilho_atual["visible_if"] == {
        "any": [
            {
                "source": "current",
                "key": "novos_casos_semelhantes",
                "operator": "equals",
                "value": "Sim",
            },
            {
                "source": "current",
                "key": "nova_pista_exposicao",
                "operator": "equals",
                "value": "Sim",
            },
        ]
    }


def test_salvar_t0_form_schema_em_arquivo_temporario(monkeypatch):
    temp_dir = PROJECT_ROOT / ".codex_tmp"
    temp_dir.mkdir(exist_ok=True)
    schema_path = temp_dir / "sfa_t0_form_schema_test.json"
    schema_path.unlink(missing_ok=True)

    schema = json.loads(serializar_t0_form_schema(carregar_t0_form_schema()))
    monkeypatch.setattr(sfa_service, "T0_FORM_SCHEMA_FILE", str(schema_path))
    schema["title"] = "T0 Ajustado em Teste"

    saved_path = salvar_t0_form_schema(schema)
    persisted = json.loads(schema_path.read_text(encoding="utf-8"))

    assert saved_path == schema_path
    assert persisted["title"] == "T0 Ajustado em Teste"
    assert persisted["instrument_version"] == "collective-v2"
    schema_path.unlink(missing_ok=True)
