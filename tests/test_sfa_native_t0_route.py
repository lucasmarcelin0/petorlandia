import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from blueprints.sfa import bp as sfa_bp
from services import sfa_service

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def native_t0_app(monkeypatch):
    schema_holder = {
        "t0": sfa_service.carregar_t0_form_schema(),
        "t10": sfa_service.carregar_t10_form_schema(),
        "t30": sfa_service.carregar_t30_form_schema(),
    }
    paciente = SimpleNamespace(
        token_acesso="token-abc",
        id_estudo="SFA-910",
        ficha_sinan="3032976",
        nome="Maria Teste",
        data_nascimento="01/01/2000",
        endereco="Rua Exemplo, 123",
        resposta_t0=None,
        respostas_t10=[],
        respostas_t30=[],
    )

    def fake_busca(token):
        return paciente if token in {paciente.token_acesso, paciente.id_estudo} else None

    def _schema_copy(stage):
        schema = dict(schema_holder[stage])
        schema["_path"] = f"config/sfa_{stage}_form.json"
        schema["_stage"] = stage
        return schema

    monkeypatch.setattr("blueprints.sfa._buscar_paciente_publico_t0", fake_busca)
    monkeypatch.setattr(sfa_service, "carregar_t0_form_schema", lambda: _schema_copy("t0"))
    monkeypatch.setattr(sfa_service, "carregar_t10_form_schema", lambda: _schema_copy("t10"))
    monkeypatch.setattr(sfa_service, "carregar_t30_form_schema", lambda: _schema_copy("t30"))

    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"))
    app.config.update(TESTING=True, SECRET_KEY="teste")
    app.jinja_env.globals["csrf_token"] = lambda: "csrf-test"
    app.register_blueprint(sfa_bp)

    return app, paciente, schema_holder


def _payload_t0():
    return {
        "cpf": "12345678900",
        "ficha_sinan": "3032976",
        "nome": "Maria Teste",
        "data_nascimento": "2000-01-01",
        "endereco": "Rua Exemplo, 123",
        "tipo_residencia": "Casa urbana",
        "diagnostico_dengue_previo": "Nao",
        "condicoes_previas": ["Nenhuma das acima"],
        "sexo_biologico": "Feminino",
        "vacinas_12_meses": ["Nenhuma"],
        "ocupacao_principal": "Estudante",
        "fuma_ou_bebe": "Nao",
        "data_inicio_sintomas": "2026-03-18",
        "teve_febre": "Sim",
        "padrao_febre": "Vai e volta",
        "sintomas_principais": ["Cansaco extremo"],
        "dor_mais_intensa": "Cabeca",
        "contato_agua_suja": "Nao",
        "contato_carrapato_mata": "Nao",
        "outras_pessoas_com_sintomas": "Nao sei",
        "contato_animais": ["Nenhum contato com animais"],
        "consumo_recente": ["Nenhum desses"],
        "atividades_recentes": ["Nenhuma dessas atividades"],
        "dias_incap": "2",
        "internacao": "Nao",
        "custo_total": "15.75",
        "ausencia_familiar": "Nao",
        "aceite_tcle": [sfa_service.T0_CONSENT_ACCEPTED],
        "observacoes_finais": "Teste automatizado",
    }


def _payload_t10():
    return {
        "cpf": "12345678900",
        "nome": "Maria Teste",
        "data_entrevista_t10": "2026-03-23",
        "classificacao_melhora": "Melhorando - Sintomas leves, em recuperacao",
        "sintomas_persistentes": ["Cansaco extremo/fadiga", "Dor de cabeca"],
        "dor_articulacoes_impacto": "Sinto dor, mas nao impede minhas atividades",
        "retornou_servico_saude": "Sim",
        "quantas_vezes_retornou": "2",
        "motivo_retorno_servico": ["Consulta de retorno/monitoramento", "Realizacao de exames"],
        "internacao_t10": "Nao",
        "diagnostico_definitivo": "Fiz exames mas ainda nao recebi resultado",
        "dias_incap_novos": "3",
        "ausencia_familiar": "Nao, ninguem mais precisa faltar",
        "custo_remedios": "10.50",
        "custo_consultas": "20.00",
        "custo_transporte": "5.25",
        "custo_outros": "2.00",
        "renda_familiar_afetada": "Sim, reducao temporaria da renda",
        "retorno_atividades_previsao": "Em 1 semana ou menos",
        "observacoes_finais": "Melhorando aos poucos",
    }


def _payload_t30():
    return {
        "cpf": "12345678900",
        "nome": "Maria Teste",
        "estado_saude_final": "Quase recuperado - 90-99% recuperado, diferencas minimas",
        "sequelas_atuais": ["Fadiga cronica (cansaco extremo que nao passa)", "Dor muscular residual"],
        "dor_articulacoes_final": "Ocorre apenas apos esforco fisico",
        "dias_incap_novos": "1",
        "retorno_atividades_normais": "75-99% retomadas - Quase normal, pequenas limitacoes",
        "custo_remedios": "0",
        "custo_consultas": "0",
        "custo_transporte": "3.50",
        "perda_renda_estimada": "120.00",
        "custo_outros": "0",
        "impacto_emocional_familiar": "Leve estresse familiar - Resolvido rapidamente",
        "conselho_outras_pessoas": "Procure atendimento cedo e descanse bastante.",
        "avaliacao_atendimento_saude": "Bom - Atendeu as necessidades",
        "participaria_outro_estudo": "Sim, com certeza - Acho importante contribuir",
        "observacoes_finais": "Recuperado",
    }


def test_public_native_t0_get_renderiza_formulario(native_t0_app):
    app, paciente, _schema_holder = native_t0_app
    client = app.test_client()

    response = client.get(f"/sfa/p/{paciente.token_acesso}")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "T0 Estudo SFA Orlandia" in html
    assert "Maria Teste" in html
    assert 'name="data_inicio_sintomas"' in html
    assert 'name="ficha_sinan"' in html
    assert 'readonly aria-readonly="true"' in html
    assert "TCLE_SFA_Orlandia_v1.docx" in html
    assert "sera usado como assinatura" in html


def test_public_native_followup_get_prefill_de_t0(native_t0_app):
    app, paciente, _schema_holder = native_t0_app
    paciente.resposta_t0 = SimpleNamespace(
        dados_json=json.dumps(
            {
                "cpf": "12345678900",
                "nome": "Maria Teste T0",
            }
        )
    )
    client = app.test_client()

    response = client.get(f"/sfa/p/{paciente.token_acesso}/t10")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'value="12345678900"' in html
    assert 'value="Maria Teste T0"' in html


def test_public_native_t0_post_envia_payload_e_mostra_sucesso(native_t0_app, monkeypatch):
    app, paciente, _schema_holder = native_t0_app
    client = app.test_client()
    captured = {}

    def fake_on_submit(dados):
        captured.update(dados)
        paciente.resposta_t0 = object()
        return {"ok": True, "id_estudo": paciente.id_estudo, "acao": "atualizado"}

    monkeypatch.setattr(sfa_service, "on_submit_t0", fake_on_submit)

    response = client.post(
        f"/sfa/p/{paciente.token_acesso}",
        data=_payload_t0(),
        headers={
            "User-Agent": "pytest-native-t0",
            "X-Forwarded-For": "203.0.113.9, 10.0.0.1",
        },
    )

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Obrigado pela sua participacao" in html
    assert captured["token_acesso"] == "token-abc"
    assert captured["id_estudo"] == "SFA-910"
    assert captured["_origem"] == "native_t0_form"
    assert captured["condicoes_previas"] == ["Nenhuma das acima"]
    assert captured["sintomas_principais"] == ["Cansaco extremo"]
    assert captured["aceite_tcle"] == [sfa_service.T0_CONSENT_ACCEPTED]
    assert captured["consentimento_ip"] == "203.0.113.9"
    assert captured["consentimento_user_agent"] == "pytest-native-t0"
    assert captured["data_inicio_sintomas"] == "18/03/2026"


def test_public_native_t0_get_apos_resposta_mostra_confirmacao(native_t0_app):
    app, paciente, _schema_holder = native_t0_app
    paciente.resposta_t0 = object()
    client = app.test_client()

    response = client.get(f"/sfa/p/{paciente.token_acesso}")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Sua resposta ja foi registrada" in html


def test_tcle_signatures_page_renderiza_lista(native_t0_app, monkeypatch):
    app, _paciente, _schema_holder = native_t0_app
    client = app.test_client()

    monkeypatch.setattr(
        sfa_service,
        "listar_assinaturas_tcle",
        lambda: [
            {
                "assinado_em": "23/03/2026 14:30",
                "id_estudo": "SFA-910",
                "ficha_sinan": "3032976",
                "participante": "Maria Teste",
                "nome_assinatura": "Maria Teste",
                "ip": "203.0.113.9",
                "user_agent": "pytest-agent",
            }
        ],
    )

    response = client.get("/sfa/tcle/assinaturas")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Registro interno de consentimento" in html
    assert "Maria Teste" in html
    assert "SFA-910" in html


@pytest.mark.parametrize(
    ("url", "expected_title"),
    [
        ("/sfa/p/token-abc/t10", "T10 Estudo SFA Orlandia"),
        ("/sfa/p/token-abc/t30", "T30 Estudo SFA Orlandia"),
    ],
)
def test_public_native_followups_get_renderiza_formulario(native_t0_app, url, expected_title):
    app, _paciente, _schema_holder = native_t0_app
    client = app.test_client()

    response = client.get(url)

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert expected_title in html


def test_public_native_t10_post_envia_payload_e_mostra_sucesso(native_t0_app, monkeypatch):
    app, paciente, _schema_holder = native_t0_app
    client = app.test_client()
    captured = {}

    def fake_on_submit(dados):
        captured.update(dados)
        paciente.respostas_t10 = [object()]
        return {"ok": True, "id_estudo": paciente.id_estudo}

    monkeypatch.setattr(sfa_service, "on_submit_t10", fake_on_submit)

    response = client.post(f"/sfa/p/{paciente.token_acesso}/t10", data=_payload_t10())

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Obrigado pela sua participacao" in html
    assert captured["id_estudo"] == "SFA-910"
    assert captured["_origem"] == "native_t10_form"
    assert captured["dias_incap_novos"] == "3"
    assert captured["sintomas_persistentes"] == ["Cansaco extremo/fadiga", "Dor de cabeca"]


def test_public_native_t30_post_envia_payload_e_mostra_sucesso(native_t0_app, monkeypatch):
    app, paciente, _schema_holder = native_t0_app
    client = app.test_client()
    captured = {}

    def fake_on_submit(dados):
        captured.update(dados)
        paciente.respostas_t30 = [object()]
        return {"ok": True, "id_estudo": paciente.id_estudo}

    monkeypatch.setattr(sfa_service, "on_submit_t30", fake_on_submit)

    response = client.post(f"/sfa/p/{paciente.token_acesso}/t30", data=_payload_t30())

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Obrigado pela sua participacao" in html
    assert captured["id_estudo"] == "SFA-910"
    assert captured["_origem"] == "native_t30_form"
    assert captured["custo_transporte"] == "3.50"
    assert captured["sequelas_atuais"] == [
        "Fadiga cronica (cansaco extremo que nao passa)",
        "Dor muscular residual",
    ]


@pytest.mark.parametrize(
    ("attr_name", "url"),
    [
        ("respostas_t10", "/sfa/p/token-abc/t10"),
        ("respostas_t30", "/sfa/p/token-abc/t30"),
    ],
)
def test_public_native_followups_get_apos_resposta_mostra_confirmacao(
    native_t0_app,
    attr_name,
    url,
):
    app, paciente, _schema_holder = native_t0_app
    setattr(paciente, attr_name, [object()])
    client = app.test_client()

    response = client.get(url)

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Sua resposta ja foi registrada" in html


def test_t0_form_config_salva_schema_editavel(native_t0_app, monkeypatch):
    app, _paciente, schema_holder = native_t0_app
    client = app.test_client()
    saved = {}

    def fake_salvar(schema):
        saved.update(schema)
        schema_holder["t0"] = dict(schema)

    monkeypatch.setattr(sfa_service, "salvar_t0_form_schema", fake_salvar)

    schema_editado = json.loads(
        sfa_service.serializar_t0_form_schema(schema_holder["t0"])
    )
    schema_editado["title"] = "T0 Editado no Painel"

    response = client.post(
        "/sfa/config/t0",
        data={"schema_json": json.dumps(schema_editado, ensure_ascii=False)},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/sfa/config/t0")
    assert saved["title"] == "T0 Editado no Painel"


@pytest.mark.parametrize(
    "url",
    [
        "/sfa/config/t0",
        "/sfa/config/t10",
        "/sfa/config/t30",
    ],
)
def test_form_config_get_renderiza_editor_visual(native_t0_app, url):
    app, _paciente, _schema_holder = native_t0_app
    client = app.test_client()

    response = client.get(url)

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Editor visual" in html
    assert "Adicionar secao" in html
    assert "schemaBuilderForm" in html


@pytest.mark.parametrize(
    ("url", "stage", "title"),
    [
        ("/sfa/config/t10", "t10", "T10 Editado no Painel"),
        ("/sfa/config/t30", "t30", "T30 Editado no Painel"),
    ],
)
def test_followup_form_configs_salvam_schema_editavel(
    native_t0_app,
    monkeypatch,
    url,
    stage,
    title,
):
    app, _paciente, schema_holder = native_t0_app
    client = app.test_client()
    saved = {}

    monkeypatch.setattr(
        sfa_service,
        f"salvar_{stage}_form_schema",
        lambda schema: saved.update(schema),
    )

    schema_editado = json.loads(
        sfa_service.serializar_t0_form_schema(schema_holder[stage])
    )
    schema_editado["title"] = title

    response = client.post(
        url,
        data={"schema_json": json.dumps(schema_editado, ensure_ascii=False)},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(url)
    assert saved["title"] == title


class _FakeExportQuery:
    def __init__(self, pacientes):
        self._pacientes = pacientes

    def all(self):
        return self._pacientes


@pytest.mark.parametrize(
    ("url", "csv_text", "expected_name"),
    [
        ("/sfa/export/cadastro.csv", "id_estudo\nSFA-910\n", "sfa_cadastro_"),
        ("/sfa/export/analitico.csv", "id_estudo\nSFA-910\n", "sfa_analitico_"),
    ],
)
def test_export_routes_retornam_csv(native_t0_app, monkeypatch, url, csv_text, expected_name):
    app, paciente, _schema_holder = native_t0_app
    client = app.test_client()

    monkeypatch.setattr("blueprints.sfa._consulta_pacientes_filtrada", lambda filtros=None: _FakeExportQuery([paciente]))
    monkeypatch.setattr(sfa_service, "gerar_csv_exportacao_cadastro", lambda pacientes: csv_text)
    monkeypatch.setattr(sfa_service, "gerar_csv_exportacao_analitica", lambda pacientes: csv_text)

    response = client.get(url)

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert expected_name in response.headers["Content-Disposition"]
    assert "SFA-910" in response.get_data(as_text=True)
