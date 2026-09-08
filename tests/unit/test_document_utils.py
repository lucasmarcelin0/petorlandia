import pytest
from document_utils import format_cnpj, only_digits


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


def test_only_digits_with_mixed_string():
    assert only_digits("123abc456") == "123456"
    assert only_digits("1a2b3c") == "123"


def test_only_digits_with_empty_string():
    assert only_digits("") == ""


def test_only_digits_with_none():
    assert only_digits(None) == ""


def test_only_digits_with_only_letters():
    assert only_digits("abc") == ""
    assert only_digits("!@#$") == ""


def test_only_digits_with_integers_or_floats():
    assert only_digits(12345) == "12345"
    assert only_digits(123.45) == "12345"


def test_only_digits_with_zero():
    assert only_digits(0) == ""
    assert only_digits("0") == "0"
