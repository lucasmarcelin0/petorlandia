from services.sfa_service import _sanitize_limited_text


def test_sanitize_limited_text_normalizes_whitespace():
    ajustes = []

    value = _sanitize_limited_text("  AVENIDA   9 \n\n 377  ", 300, "endereco", ajustes)

    assert value == "AVENIDA 9 377"
    assert ajustes == [
        {
            "campo": "endereco",
            "acao": "normalizado",
            "tamanho_original": 22,
            "tamanho_final": 13,
        }
    ]


def test_sanitize_limited_text_truncates_long_values():
    ajustes = []

    value = _sanitize_limited_text("X" * 350, 300, "endereco", ajustes)

    assert len(value) == 300
    assert ajustes == [
        {
            "campo": "endereco",
            "acao": "truncado",
            "tamanho_original": 350,
            "tamanho_final": 300,
        }
    ]
