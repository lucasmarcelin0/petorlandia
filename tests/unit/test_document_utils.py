import pytest
from document_utils import format_cnpj

def test_format_cnpj_happy_path():
    assert format_cnpj("12345678901234") == "12.345.678/9012-34"

def test_format_cnpj_already_formatted_mixed_characters():
    assert format_cnpj("12.345.678/9012-34") == "12.345.678/9012-34"
    assert format_cnpj("abc12345678901234") == "12.345.678/9012-34"
    assert format_cnpj("  12345678901234  ") == "12.345.678/9012-34"

def test_format_cnpj_invalid_length():
    assert format_cnpj("123") == "123"
    assert format_cnpj("1234567890123") == "1234567890123"
    assert format_cnpj("123456789012345") == "123456789012345"

def test_format_cnpj_edge_cases():
    assert format_cnpj("") == ""
    assert format_cnpj("   ") == ""
    assert format_cnpj(None) == ""
