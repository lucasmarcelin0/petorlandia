from pathlib import Path

import pytest
from flask import Flask

from blueprints.sfa import bp as sfa_bp

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"),
                static_folder=str(PROJECT_ROOT / "static"))
    app.config.update(TESTING=True, SECRET_KEY="teste")
    app.jinja_env.globals["csrf_token"] = lambda: "csrf-test"
    app.register_blueprint(sfa_bp)
    return app.test_client()


def test_pre_t0_form_renders_item_lists(client):
    # Regressão: "field.items" no Jinja resolvia para o método dict.items.
    response = client.get("/sfa/pre-t0")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="sinais_clinicos__febre"' in html
    assert 'name="doencas_preexistentes__diabetes"' in html
    assert 'name="sinais_alarme__queda_plaquetas"' in html
    assert 'name="investigador__nome"' in html
    assert 'name="dengue_grave__melena"' in html
    assert response.headers["Cache-Control"] == "no-store, private"


def test_pre_t0_form_keeps_item_answers_after_validation_error(client):
    response = client.post("/sfa/pre-t0", data={
        "sinais_clinicos__febre": "1",
        "sinais_alarme__queda_plaquetas": "1",
        "investigador__nome": "Equipe Teste",
    })

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="sinais_clinicos__febre" value="1" checked' in html
    assert 'name="sinais_alarme__queda_plaquetas" value="1" checked' in html
    assert 'value="Equipe Teste"' in html
