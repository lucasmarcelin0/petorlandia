import pytest
import requests
from unittest.mock import patch, MagicMock

from helpers import reverse_geocode_city

def test_reverse_geocode_invalid_input():
    # Should return None for non-floatable coordinates
    assert reverse_geocode_city("invalid", "invalid") is None
    assert reverse_geocode_city(None, None) is None
    assert reverse_geocode_city(10, None) is None

@patch("helpers.requests.get")
def test_reverse_geocode_success_city(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {"address": {"city": "Belo Horizonte"}}
    mock_get.return_value = mock_response

    assert reverse_geocode_city(-19.9, -43.9) == "Belo Horizonte"

    # Verify requests.get was called with correct parameters
    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args[0] == "https://nominatim.openstreetmap.org/reverse"
    assert kwargs["params"]["lat"] == -19.9
    assert kwargs["params"]["lon"] == -43.9

@patch("helpers.requests.get")
def test_reverse_geocode_fallback_keys(mock_get):
    # Test alternative keys sequentially as defined in helpers.py
    keys = ["town", "municipality", "village", "county"]

    for key in keys:
        mock_response = MagicMock()
        mock_response.json.return_value = {"address": {key: "SampleCity"}}
        mock_get.return_value = mock_response

        assert reverse_geocode_city(10.0, 20.0) == "SampleCity"

@patch("helpers.requests.get")
def test_reverse_geocode_missing_address_or_city(mock_get):
    # Empty response
    mock_response = MagicMock()
    mock_response.json.return_value = {}
    mock_get.return_value = mock_response
    assert reverse_geocode_city(10.0, 20.0) is None

    # Response with empty address
    mock_response.json.return_value = {"address": {}}
    assert reverse_geocode_city(10.0, 20.0) is None

    # Response with address but no city keys
    mock_response.json.return_value = {"address": {"country": "Brazil", "state": "MG"}}
    assert reverse_geocode_city(10.0, 20.0) is None

@patch("helpers.requests.get")
def test_reverse_geocode_invalid_json(mock_get):
    # Mock json() raising ValueError
    mock_response = MagicMock()
    mock_response.json.side_effect = ValueError("Invalid JSON")
    mock_get.return_value = mock_response

    assert reverse_geocode_city(10.0, 20.0) is None

@patch("helpers.requests.get")
def test_reverse_geocode_request_exception(mock_get):
    # Mock requests.get raising an exception
    mock_get.side_effect = requests.RequestException("Network error")

    assert reverse_geocode_city(10.0, 20.0) is None

@patch("helpers.requests.get")
def test_reverse_geocode_raise_for_status(mock_get):
    # Mock response.raise_for_status() raising an exception
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
    mock_get.return_value = mock_response

    assert reverse_geocode_city(10.0, 20.0) is None
