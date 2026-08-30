"""Unit tests for security.url_safe SSRF validation module."""
import pytest
from security.url_safe import is_url_ssrf_safe


def test_is_url_ssrf_safe_valid_urls(monkeypatch):
    # Mock socket.getaddrinfo to return public IP
    import socket
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    assert is_url_ssrf_safe("https://example.com/image.jpg") is True
    assert is_url_ssrf_safe("http://example.org/path?query=1") is True


def test_is_url_ssrf_safe_invalid_scheme():
    assert is_url_ssrf_safe("file:///etc/passwd") is False
    assert is_url_ssrf_safe("ftp://example.com/file") is False
    assert is_url_ssrf_safe("javascript:alert(1)") is False
    assert is_url_ssrf_safe("") is False
    assert is_url_ssrf_safe(None) is False


def test_is_url_ssrf_safe_private_ips():
    assert is_url_ssrf_safe("http://127.0.0.1/secret") is False
    assert is_url_ssrf_safe("http://localhost/secret") is False
    assert is_url_ssrf_safe("http://10.0.0.1/admin") is False
    assert is_url_ssrf_safe("http://192.168.1.1/") is False
    assert is_url_ssrf_safe("http://169.254.169.254/latest/meta-data/") is False


def test_is_url_ssrf_safe_hostname_resolving_to_private_ip(monkeypatch):
    import socket
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    assert is_url_ssrf_safe("https://internal.localdomain/data") is False
