from unittest.mock import patch, MagicMock
import requests
from helpers import geocode_address


def _mock_response(status_code=200, json_data=None, side_effect=None):
    mock = MagicMock()
    mock.status_code = status_code
    if side_effect:
        mock.raise_for_status.side_effect = side_effect
    else:
        mock.raise_for_status.return_value = None
    mock.json.return_value = json_data if json_data is not None else []
    return mock


def test_geocode_address_structured_success():
    resp = _mock_response(200, [{'lat': '-23.5505', 'lon': '-46.6333'}])
    with patch.object(requests.Session, 'get', return_value=resp) as mock_get:
        coords = geocode_address(rua='Avenida Paulista', numero='1578', cidade='São Paulo', estado='SP')
        assert coords == (-23.5505, -46.6333)
        assert mock_get.called
        call_params = mock_get.call_args[1]['params']
        assert call_params['city'] == 'São Paulo'
        assert call_params['state'] == 'SP'


def test_geocode_address_fallback_to_free_text():
    empty_resp = _mock_response(200, [])
    success_resp = _mock_response(200, [{'lat': '-23.5500', 'lon': '-46.6300'}])
    # Returns empty for structured queries, then success for free-text fallback
    with patch.object(requests.Session, 'get', side_effect=[empty_resp, empty_resp, empty_resp, success_resp]):
        coords = geocode_address(rua='Rua Inexistente', numero='999', bairro='Bairro X', cidade='São Paulo', estado='SP')
        assert coords == (-23.5500, -46.6300)


def test_geocode_address_request_exception():
    with patch.object(requests.Session, 'get', side_effect=requests.Timeout('Connection timed out')):
        coords = geocode_address(cidade='São Paulo', estado='SP')
        assert coords is None


def test_geocode_address_malformed_response():
    resp = _mock_response(200, [{'name': 'São Paulo'}])  # Missing lat/lon
    with patch.object(requests.Session, 'get', return_value=resp):
        coords = geocode_address(cidade='São Paulo', estado='SP')
        assert coords is None


def test_geocode_address_empty_response():
    resp = _mock_response(200, [])
    with patch.object(requests.Session, 'get', return_value=resp):
        coords = geocode_address(cidade='Nowhere', estado='NX')
        assert coords is None


def test_geocode_address_empty_arguments():
    resp = _mock_response(200, [{'lat': '-10.0', 'lon': '-50.0'}])
    with patch.object(requests.Session, 'get', return_value=resp) as mock_get:
        coords = geocode_address()
        assert coords == (-10.0, -50.0)
        call_params = mock_get.call_args[1]['params']
        assert call_params['q'] == 'Brasil'
