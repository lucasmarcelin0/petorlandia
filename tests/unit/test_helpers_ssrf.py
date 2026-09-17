"""Unit tests for SSRF validation in helpers.py geocoding functions."""

from unittest.mock import patch
from helpers import reverse_geocode_city, geocode_address


def test_reverse_geocode_city_ssrf_blocked():
    """Test that reverse_geocode_city returns None when SSRF validation fails."""
    with patch("helpers.is_url_ssrf_safe", return_value=False), \
         patch("helpers.requests.get") as mock_get:
        result = reverse_geocode_city(-20.7186, -47.8824)
        assert result is None
        mock_get.assert_not_called()


def test_geocode_address_ssrf_blocked():
    """Test that geocode_address returns None when SSRF validation fails."""
    with patch("helpers.is_url_ssrf_safe", return_value=False), \
         patch("helpers.requests.Session") as mock_session_class:
        result = geocode_address(cidade="Orlândia", estado="SP")
        assert result is None
        mock_session_class.return_value.get.assert_not_called()
