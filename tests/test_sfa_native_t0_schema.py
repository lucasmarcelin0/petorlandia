import json
from types import SimpleNamespace

from werkzeug.datastructures import MultiDict

from services import sfa_service
from services.sfa_service import (
    carregar_t10_form_schema,
    carregar_t30_form_schema,
    carregar_t0_form_schema,
    construir_valores_iniciais_t10,
    construir_valores_iniciais_t30,
    coletar_resposta_t0_nativa,
    construir_valores_iniciais_t0,
    salvar_t0_form_schema,
    serializar_t0_form_schema,
)


def _paciente_fake():
    return SimpleNamespace(
        token_acesso="token-abc",
        id_estudo="SFA-900",
        ficha_sinan="3032976",
        nome="Maria Teste",
        data_nascimento="01/01/2000",
        endereco="Rua Exemplo, 123",
        resposta_t0=None,
        respostas_t10=[],
        respostas_t30=[],
    )


def test_carregar_t0_form_schema_tem_campos_esperados():
    schema = carregar_t0_form_schema()

    assert schema["title"] == "T0 Estudo SFA Orlandia"
    assert any(field["key"] == "nome" for section in schema["sections"] for field in section["fields"])
    assert any(field["key"] == "custo_total" for section in schema["sections"] for field in section["fields"])
    assert any(field["key"] == "aceite_tcle" for section in schema["sections"] for field in section["fields"])


def test_carregar_t10_t30_form_schemas_tem_campos_esperados():
    schema_t10 = carregar_t10_form_schema()
    schema_t30 = carregar_t30_form_schema()

    assert schema_t10["title"] == "T10 Estudo SFA Orlandia"
    assert schema_t30["title"] == "T30 Estudo SFA Orlandia"
    assert any(field["key"] == "classificacao_melhora" for section in schema_t10["sections"] for field in section["fields"])
    assert any(field["key"] == "dias_incap_novos" for section in schema_t10["sections"] for field in section["fields"])
    assert any(field["key"] == "estado_saude_final" for section in schema_t30["sections"] for field in section["fields"])
    assert any(field["key"] == "custo_transporte" for section in schema_t30["sections"] for field in section["fields"])


def test_construir_valores_iniciais_t0_prefill_paciente():
    values = construir_valores_iniciais_t0(_paciente_fake(), carregar_t0_form_schema())

    assert values["ficha_sinan"] == "3032976"
    assert values["nome"] == "Maria Teste"
    assert values["data_nascimento"] == "2000-01-01"
    assert values["endereco"] == "Rua Exemplo, 123"


def test_construir_valores_iniciais_followups_prefill_de_resposta_anterior():
    paciente = _paciente_fake()
    paciente.nome = "Nome no cadastro"
    paciente.resposta_t0 = SimpleNamespace(
        dados_json=json.dumps(
            {
                "cpf": "12345678900",
                "nome": "Nome informado no T0",
            }
        )
    )

    values_t10 = construir_valores_iniciais_t10(paciente, carregar_t10_form_schema())
    values_t30 = construir_valores_iniciais_t30(paciente, carregar_t30_form_schema())

    assert values_t10["cpf"] == "12345678900"
    assert values_t10["nome"] == "Nome informado no T0"
    assert values_t30["cpf"] == "12345678900"
    assert values_t30["nome"] == "Nome informado no T0"


def test_coletar_resposta_t0_nativa_normaliza_payload():
    form_data = MultiDict(
        [
            ("cpf", "12345678900"),
            ("ficha_sinan", "3032976"),
            ("nome", "Maria Teste"),
            ("data_nascimento", "2000-01-01"),
            ("endereco", "Rua Exemplo, 123"),
            ("tipo_residencia", "Casa urbana"),
            ("diagnostico_dengue_previo", "Nao"),
            ("condicoes_previas", "Nenhuma das acima"),
            ("sexo_biologico", "Feminino"),
            ("vacinas_12_meses", "Nenhuma"),
            ("ocupacao_principal", "Estudante"),
            ("fuma_ou_bebe", "Nao"),
            ("data_inicio_sintomas", "2026-03-18"),
            ("teve_febre", "Sim"),
            ("padrao_febre", "Vai e volta"),
            ("sintomas_principais", "Cansaco extremo"),
            ("dor_mais_intensa", "Cabeca"),
            ("contato_agua_suja", "Nao"),
            ("contato_carrapato_mata", "Nao"),
            ("outras_pessoas_com_sintomas", "Nao sei"),
            ("contato_animais", "Nenhum contato com animais"),
            ("consumo_recente", "Nenhum desses"),
            ("atividades_recentes", "Nenhuma dessas atividades"),
            ("dias_incap", "2"),
            ("internacao", "Nao"),
            ("custo_total", "15.75"),
            ("ausencia_familiar", "Nao"),
            ("aceite_tcle", sfa_service.T0_CONSENT_ACCEPTED),
            ("observacoes_finais", "Teste automatizado"),
        ]
    )

    dados, errors = coletar_resposta_t0_nativa(
        carregar_t0_form_schema(),
        form_data,
        _paciente_fake(),
    )

    assert errors == {}
    assert dados["token_acesso"] == "token-abc"
    assert dados["id_estudo"] == "SFA-900"
    assert dados["ficha_sinan"] == "3032976"
    assert dados["data_nascimento"] == "01/01/2000"
    assert dados["data_inicio_sintomas"] == "18/03/2026"
    assert dados["condicoes_previas"] == ["Nenhuma das acima"]
    assert dados["sintomas_principais"] == ["Cansaco extremo"]
    assert dados["aceite_tcle"] == [sfa_service.T0_CONSENT_ACCEPTED]


def test_coletar_resposta_t0_nativa_exige_aceite_do_tcle():
    form_data = MultiDict(
        [
            ("nome", "Maria Teste"),
            ("data_nascimento", "2000-01-01"),
            ("endereco", "Rua Exemplo, 123"),
            ("tipo_residencia", "Casa urbana"),
            ("diagnostico_dengue_previo", "Nao"),
            ("condicoes_previas", "Nenhuma das acima"),
            ("sexo_biologico", "Feminino"),
            ("vacinas_12_meses", "Nenhuma"),
            ("ocupacao_principal", "Estudante"),
            ("fuma_ou_bebe", "Nao"),
            ("data_inicio_sintomas", "2026-03-18"),
            ("teve_febre", "Sim"),
            ("padrao_febre", "Vai e volta"),
            ("sintomas_principais", "Cansaco extremo"),
            ("dor_mais_intensa", "Cabeca"),
            ("contato_agua_suja", "Nao"),
            ("contato_carrapato_mata", "Nao"),
            ("outras_pessoas_com_sintomas", "Nao sei"),
            ("contato_animais", "Nenhum contato com animais"),
            ("consumo_recente", "Nenhum desses"),
            ("atividades_recentes", "Nenhuma dessas atividades"),
            ("dias_incap", "2"),
            ("internacao", "Nao"),
            ("custo_total", "15.75"),
            ("ausencia_familiar", "Nao"),
        ]
    )

    _dados, errors = coletar_resposta_t0_nativa(
        carregar_t0_form_schema(),
        form_data,
        _paciente_fake(),
    )

    assert errors["aceite_tcle"] == "Voce precisa aceitar o TCLE para enviar o formulario."


def test_salvar_t0_form_schema_em_arquivo_temporario(monkeypatch, tmp_path):
    schema_path = tmp_path / "sfa_t0_form.json"
    schema = json.loads(serializar_t0_form_schema(carregar_t0_form_schema()))
    monkeypatch.setattr(sfa_service, "T0_FORM_SCHEMA_FILE", str(schema_path))
    schema["title"] = "T0 Ajustado em Teste"

    saved_path = salvar_t0_form_schema(schema)
    persisted = json.loads(schema_path.read_text(encoding="utf-8"))

    assert saved_path == schema_path
    assert persisted["title"] == "T0 Ajustado em Teste"
