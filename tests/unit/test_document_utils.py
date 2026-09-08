import pytest
from document_utils import only_digits

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
    # Due to `str(value or "")`, integer 0 becomes "" instead of "0"
    assert only_digits(0) == ""
    assert only_digits("0") == "0"
