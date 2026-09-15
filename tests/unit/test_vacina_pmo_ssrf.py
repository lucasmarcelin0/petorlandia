from unittest.mock import patch
from services.vacina_pmo_service import _pmo_geocode_google, _pmo_geocode_address


def test_pmo_google_geocode_ssrf_blocked():
    with patch("services.vacina_pmo_service.is_url_ssrf_safe", return_value=False):
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "fake_key"}):
            coords = _pmo_geocode_google("Rua 1, Orlandia")
            assert coords is None


def test_pmo_geocode_address_ssrf_blocked():
    with patch("services.vacina_pmo_service.is_url_ssrf_safe", return_value=False):
        # When nominatim_url is not ssrf safe, it falls back to local geocode or returns coords from local geocode
        coords = _pmo_geocode_address("Rua 1, 100, Centro, Orlândia")
        # Local geocode for Rua 1 + 100 should return coords
        assert coords is not None
        # Verify that requests.Session.get or requests.get were not called
        with patch("requests.get") as mock_get, patch("requests.Session.get") as mock_sess_get:
            coords2 = _pmo_geocode_address("Rua 1, 100, Centro, Orlândia")
            assert mock_get.call_count == 0
            assert mock_sess_get.call_count == 0
