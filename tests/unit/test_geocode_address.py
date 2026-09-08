import pytest
import requests
import responses
from helpers import geocode_address

@responses.activate
def test_geocode_address_structured_success():
    """Test successful geocoding using structured query parameters."""
    responses.add(
        responses.GET,
        "https://nominatim.openstreetmap.org/search",
        json=[{"lat": "-23.5505", "lon": "-46.6333"}],
        status=200,
        match=[
            responses.matchers.query_param_matcher({
                "city": "São Paulo",
                "state": "SP",
                "country": "Brasil",
                "street": "Avenida Paulista 1578",
                "format": "json",
                "limit": "1",
                "countrycodes": "br"
            })
        ]
    )

    coords = geocode_address(rua="Avenida Paulista", numero="1578", cidade="São Paulo", estado="SP")
    assert coords == (-23.5505, -46.6333)


@responses.activate
def test_geocode_address_fallback_to_free_text():
    """Test falling back to free-text search when structured query fails."""
    # First structured query fails (returns empty list)
    responses.add(
        responses.GET,
        "https://nominatim.openstreetmap.org/search",
        json=[],
        status=200,
        match=[
            responses.matchers.query_param_matcher({
                "city": "São Paulo",
                "state": "SP",
                "country": "Brasil",
                "street": "Rua Inexistente 999",
                "format": "json",
                "limit": "1",
                "countrycodes": "br"
            })
        ]
    )

    # Second structured query (without number) fails
    responses.add(
        responses.GET,
        "https://nominatim.openstreetmap.org/search",
        json=[],
        status=200,
        match=[
            responses.matchers.query_param_matcher({
                "city": "São Paulo",
                "state": "SP",
                "country": "Brasil",
                "street": "Rua Inexistente",
                "format": "json",
                "limit": "1",
                "countrycodes": "br"
            })
        ]
    )

    # Third structured query (bairro + city) fails
    responses.add(
        responses.GET,
        "https://nominatim.openstreetmap.org/search",
        json=[],
        status=200,
        match=[
            responses.matchers.query_param_matcher({
                "city": "São Paulo",
                "state": "SP",
                "country": "Brasil",
                "county": "Bairro X",
                "format": "json",
                "limit": "1",
                "countrycodes": "br"
            })
        ]
    )

    # Free text fallback succeeds
    responses.add(
        responses.GET,
        "https://nominatim.openstreetmap.org/search",
        json=[{"lat": "-23.5500", "lon": "-46.6300"}],
        status=200,
        match=[
            responses.matchers.query_param_matcher({
                "q": "Rua Inexistente, 999, Bairro X, São Paulo, SP, Brasil",
                "format": "json",
                "limit": "1",
                "countrycodes": "br"
            })
        ]
    )

    coords = geocode_address(rua="Rua Inexistente", numero="999", bairro="Bairro X", cidade="São Paulo", estado="SP")
    assert coords == (-23.5500, -46.6300)


@responses.activate
def test_geocode_address_request_exception():
    """Test handling of request exceptions (e.g., timeout)."""
    responses.add(
        responses.GET,
        "https://nominatim.openstreetmap.org/search",
        body=requests.Timeout("Connection timed out")
    )

    coords = geocode_address(cidade="São Paulo", estado="SP")
    assert coords is None

@responses.activate
def test_geocode_address_malformed_response():
    """Test handling of malformed responses missing coordinate data."""
    responses.add(
        responses.GET,
        "https://nominatim.openstreetmap.org/search",
        json=[{"name": "São Paulo"}],  # Missing lat/lon
        status=200
    )

    coords = geocode_address(cidade="São Paulo", estado="SP")
    assert coords is None

@responses.activate
def test_geocode_address_empty_response():
    """Test handling of valid but empty responses when all queries fail."""
    responses.add(
        responses.GET,
        "https://nominatim.openstreetmap.org/search",
        json=[],
        status=200
    )

    coords = geocode_address(cidade="Nowhere", estado="NX")
    assert coords is None

@responses.activate
def test_geocode_address_empty_arguments():
    """Test calling geocode_address without arguments."""
    responses.add(
        responses.GET,
        "https://nominatim.openstreetmap.org/search",
        json=[{"lat": "-10.0", "lon": "-50.0"}],
        status=200,
        match=[
            responses.matchers.query_param_matcher({
                "q": "Brasil",
                "format": "json",
                "limit": "1",
                "countrycodes": "br"
            })
        ]
    )

    coords = geocode_address()
    assert coords == (-10.0, -50.0)
