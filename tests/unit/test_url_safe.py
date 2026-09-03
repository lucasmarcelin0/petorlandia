"""Unit tests for security/url_safe.py."""

from unittest.mock import patch
import socket
import pytest

from security.url_safe import is_url_ssrf_safe


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
