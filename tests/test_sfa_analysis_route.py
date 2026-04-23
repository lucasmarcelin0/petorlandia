import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from blueprints.sfa import bp as sfa_bp

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FakeExportQuery:
    def __init__(self, pacientes):
        self._pacientes = pacientes

    def all(self):
        return self._pacientes


@pytest.fixture()
def analysis_app():
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"))
    app.config.update(TESTING=True, SECRET_KEY="teste")
    app.jinja_env.globals["csrf_token"] = lambda: "csrf-test"
    app.register_blueprint(sfa_bp)
    return app


def test_analise_respostas_remove_pacientes_de_teste(analysis_app, monkeypatch):
    client = analysis_app.test_client()
    captured = {}

    real = SimpleNamespace(
        id_estudo="SFA-REAL",
        nome="Paciente Real",
        grupo="A",
        bairro="Centro",
        data_nascimento="01/01/1990",
        data_t0="20/03/2026",
        data_t10="30/03/2026",
        data_t30="19/04/2026",
        resposta_t0=SimpleNamespace(
            data_inicio_sintomas="18/03/2026",
            dados_json=json.dumps({"data_inicio_sintomas": "18/03/2026"}),
        ),
        respostas_t10=[],
        respostas_t30=[],
        observacao_operacional="",
        ficha_sinan="3032976",
        token_acesso="real-token",
    )
    teste = SimpleNamespace(
        id_estudo="SFA-TESTE",
        nome="Paciente Teste",
        grupo="B",
        bairro="Centro",
        data_nascimento="01/01/1990",
        data_t0="20/03/2026",
        data_t10="30/03/2026",
        data_t30="19/04/2026",
        resposta_t0=SimpleNamespace(
            data_inicio_sintomas="18/03/2026",
            dados_json=json.dumps({"_sfa_test_batch": "teste-20260422", "data_inicio_sintomas": "18/03/2026"}),
        ),
        respostas_t10=[],
        respostas_t30=[],
        observacao_operacional="",
        ficha_sinan="TESTE-123",
        token_acesso="teste-lote-01",
    )

    def fake_consulta(filtros=None):
        captured.update(filtros or {})
        return _FakeExportQuery([real, teste])

    monkeypatch.setattr("blueprints.sfa._consulta_pacientes_filtrada", fake_consulta)

    response = client.get("/sfa/analise-respostas?visao=testes")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert captured["visao"] == "reais"
    assert "Paciente Real" in html
    assert "Paciente Teste" not in html
