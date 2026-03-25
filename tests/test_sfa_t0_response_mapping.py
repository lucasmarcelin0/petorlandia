from services.sfa_service import (
    FORM_T0_HEADER_ALIASES,
    _build_header_lookup,
    _lookup_form_value,
    _safe_decimal_text,
    _safe_int,
    _t0_response_keys,
)


def test_lookup_form_value_matches_human_headers():
    headers = [
        "Carimbo de data/hora",
        "Token de acesso",
        "Codigo do participante",
        "Nome completo",
        "Data de nascimento",
    ]
    row = [
        "18/03/2026 09:00:00",
        "abc123token",
        "SFA-001",
        "Maria Teste",
        "01/01/2000",
    ]
    lookup = _build_header_lookup(headers)

    assert _lookup_form_value(row, lookup, FORM_T0_HEADER_ALIASES["token_acesso"]) == "abc123token"
    assert _lookup_form_value(row, lookup, FORM_T0_HEADER_ALIASES["id_estudo"]) == "SFA-001"
    assert _lookup_form_value(row, lookup, FORM_T0_HEADER_ALIASES["nome"]) == "Maria Teste"


def test_lookup_form_value_matches_numbered_headers():
    headers = [
        "Carimbo de data/hora",
        "Número da Ficha SINAN",
        "1. Nome completo",
        "2. Data de nascimento",
    ]
    row = [
        "18/03/2026 09:00:00",
        "3032976",
        "Maria Teste",
        "01/01/2000",
    ]
    lookup = _build_header_lookup(headers)

    assert _lookup_form_value(row, lookup, FORM_T0_HEADER_ALIASES["ficha_sinan"]) == "3032976"
    assert _lookup_form_value(row, lookup, FORM_T0_HEADER_ALIASES["nome"]) == "Maria Teste"
    assert _lookup_form_value(row, lookup, FORM_T0_HEADER_ALIASES["data_nascimento"]) == "01/01/2000"


def test_safe_parsers_and_t0_keys():
    assert _safe_int("12 dias") == 12
    assert _safe_decimal_text("1.234,56") == "1234.56"
    assert _t0_response_keys("abc123token", "SFA-001", "3032976", "Maria Teste", "01/01/2000") == {
        "tk:abc123token",
        "id:SFA-001",
        "fs:3032976",
        "nd:maria teste|01/01/2000",
    }
