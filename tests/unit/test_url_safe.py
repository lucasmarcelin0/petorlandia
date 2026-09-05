"""Unit tests for security/url_safe.py."""

from unittest.mock import MagicMock, patch
import socket
import pytest

from security.url_safe import (
    ExternalFetchError,
    UnsafeExternalURL,
    is_url_ssrf_safe,
    safe_fetch_url,
)


def test_is_url_ssrf_safe_valid_public_ip():
    assert is_url_ssrf_safe("https://8.8.8.8/image.jpg") is True
    assert is_url_ssrf_safe("http://1.1.1.1/test") is True


def test_is_url_ssrf_safe_private_ips():
    assert is_url_ssrf_safe("http://127.0.0.1/secret") is False
    assert is_url_ssrf_safe("http://10.0.0.1/admin") is False
    assert is_url_ssrf_safe("http://172.16.0.1/internal") is False
    assert is_url_ssrf_safe("http://192.168.1.1/router") is False
    assert is_url_ssrf_safe("http://169.254.169.254/latest/meta-data/") is False
    assert is_url_ssrf_safe("http://[::1]/") is False


def test_is_url_ssrf_safe_invalid_schemes():
    assert is_url_ssrf_safe("file:///etc/passwd") is False
    assert is_url_ssrf_safe("ftp://example.com/file") is False
    assert is_url_ssrf_safe("gopher://example.com/") is False
    assert is_url_ssrf_safe("javascript:alert(1)") is False
    assert is_url_ssrf_safe("https://example.com:8443/image.jpg") is False
    assert is_url_ssrf_safe("https://user:secret@example.com/image.jpg") is False


def test_is_url_ssrf_safe_invalid_input():
    assert is_url_ssrf_safe("") is False
    assert is_url_ssrf_safe(None) is False
    assert is_url_ssrf_safe("not_a_url") is False


@patch("socket.getaddrinfo")
def test_is_url_ssrf_safe_dns_resolution(mock_getaddrinfo):
    # Mock domain resolving to public IP
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
    ]
    assert is_url_ssrf_safe("https://example.com/photo.jpg") is True

    # Mock domain resolving to loopback IP (DNS rebinding / local resolution)
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
    ]
    assert is_url_ssrf_safe("https://localhost.example.com/") is False


@patch("socket.getaddrinfo")
def test_is_url_ssrf_safe_dns_failure(mock_getaddrinfo):
    mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")
    assert is_url_ssrf_safe("https://nonexistent-domain-xyz.com/") is False


@patch("security.url_safe.HTTPSConnectionPool")
@patch("security.url_safe.socket.getaddrinfo")
def test_safe_fetch_pins_validated_ip_and_preserves_tls_hostname(mock_dns, mock_pool_cls):
    mock_dns.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
    ]
    response = MagicMock()
    response.status = 200
    response.headers = {"Content-Type": "image/jpeg", "Content-Length": "3"}
    response.read.return_value = b"img"
    mock_pool_cls.return_value.urlopen.return_value = response

    result = safe_fetch_url("https://images.example.com/pet.jpg?v=1", max_bytes=8)

    assert result.content == b"img"
    args, kwargs = mock_pool_cls.call_args
    assert args[0] == "93.184.216.34"
    assert kwargs["assert_hostname"] == "images.example.com"
    assert kwargs["server_hostname"] == "images.example.com"
    mock_pool_cls.return_value.urlopen.assert_called_once()
    request_args, request_kwargs = mock_pool_cls.return_value.urlopen.call_args
    assert request_args[:2] == ("GET", "/pet.jpg?v=1")
    assert request_kwargs["redirect"] is False
    assert request_kwargs["headers"]["Host"] == "images.example.com"


@patch("security.url_safe.HTTPSConnectionPool")
@patch("security.url_safe.socket.getaddrinfo")
def test_safe_fetch_rejects_redirects(mock_dns, mock_pool_cls):
    mock_dns.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
    ]
    response = MagicMock()
    response.status = 302
    response.headers = {"Location": "http://127.0.0.1/admin"}
    mock_pool_cls.return_value.urlopen.return_value = response

    with pytest.raises(UnsafeExternalURL, match="Redirecionamentos"):
        safe_fetch_url("https://images.example.com/pet.jpg")


@patch("security.url_safe.HTTPSConnectionPool")
@patch("security.url_safe.socket.getaddrinfo")
def test_safe_fetch_enforces_response_size(mock_dns, mock_pool_cls):
    mock_dns.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
    ]
    response = MagicMock()
    response.status = 200
    response.headers = {"Content-Length": "100"}
    mock_pool_cls.return_value.urlopen.return_value = response

    with pytest.raises(ExternalFetchError, match="excede"):
        safe_fetch_url("https://images.example.com/pet.jpg", max_bytes=8)


@patch("security.url_safe.socket.getaddrinfo")
def test_safe_fetch_rejects_mixed_public_and_private_dns(mock_dns):
    mock_dns.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ]

    with pytest.raises(UnsafeExternalURL, match="privado"):
        safe_fetch_url("https://images.example.com/pet.jpg")


def test_mcp_integration_download_helpers_ssrf_protection():
    from app import _integration_download_and_store_carteirinha_file, _integration_download_and_store_laudo_file

    unsafe_urls = [
        "https://127.0.0.1/laudo.pdf",
        "https://10.0.0.1/laudo.pdf",
        "https://169.254.169.254/latest/meta-data/",
        "https://localhost/carteirinha.jpg",
    ]

    for url in unsafe_urls:
        with pytest.raises(ValueError, match="download_url invalido"):
            _integration_download_and_store_laudo_file({"download_url": url})

        with pytest.raises(ValueError, match="URL HTTPS autorizada"):
            _integration_download_and_store_carteirinha_file({"download_url": url})
