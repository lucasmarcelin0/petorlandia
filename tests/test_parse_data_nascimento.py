from datetime import datetime
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from helpers import parse_data_nascimento


def test_parse_data_nascimento_valid():
    assert parse_data_nascimento('15/04/2020') == datetime(2020, 4, 15)


def test_parse_data_nascimento_invalid_format():
    assert parse_data_nascimento('2020-04-15') is None
    assert parse_data_nascimento('15/4/20') is None
    assert parse_data_nascimento('invalid text') is None


def test_parse_data_nascimento_invalid_date():
    assert parse_data_nascimento('32/01/2020') is None
    assert parse_data_nascimento('29/02/2021') is None


def test_parse_data_nascimento_empty_string():
    assert parse_data_nascimento('') is None


def test_parse_data_nascimento_none():
    assert parse_data_nascimento(None) is None


def test_parse_data_nascimento_invalid_type():
    assert parse_data_nascimento(12345678) is None
    assert parse_data_nascimento({'date': '15/04/2020'}) is None
