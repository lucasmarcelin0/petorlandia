import pytest
from app_factory import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        yield app


def test_parse_concentracao_ratio(app):
    from blueprints.consulta import _parse_concentracao_string

    val, un = _parse_concentracao_string("250 mg / 5 mL")
    assert val == 50.0
    assert un == "mg/ml"

    val, un = _parse_concentracao_string("250mg/5ml")
    assert val == 50.0
    assert un == "mg/ml"

    val, un = _parse_concentracao_string("1 g / 2 mL")
    assert val == 0.5
    assert un == "g/ml"


def test_parse_concentracao_compound(app):
    from blueprints.consulta import _parse_concentracao_string

    val, un = _parse_concentracao_string("50 mg/mL")
    assert val == 50.0
    assert un == "mg/ml"

    val, un = _parse_concentracao_string("100 mcg/ml")
    assert val == 100.0
    assert un == "mcg/ml"

    val, un = _parse_concentracao_string("5 %")
    assert val == 5.0
    assert un == "%"


def test_parse_concentracao_single(app):
    from blueprints.consulta import _parse_concentracao_string

    val, un = _parse_concentracao_string("500 mg")
    assert val == 500.0
    assert un == "mg"

    val, un = _parse_concentracao_string("0,5 g")
    assert val == 0.5
    assert un == "g"

    val, un = _parse_concentracao_string("5000 UI")
    assert val == 5000.0
    assert un == "ui"


def test_parse_concentracao_numeric(app):
    from blueprints.consulta import _parse_concentracao_string

    val, un = _parse_concentracao_string("10")
    assert val == 10.0
    assert un == "mg"

    val, un = _parse_concentracao_string("12.5")
    assert val == 12.5
    assert un == "mg"


def test_parse_concentracao_empty_and_invalid(app):
    from blueprints.consulta import _parse_concentracao_string

    assert _parse_concentracao_string("") == (None, None)
    assert _parse_concentracao_string(None) == (None, None)
    assert _parse_concentracao_string("texto sem numero") == (None, None)
