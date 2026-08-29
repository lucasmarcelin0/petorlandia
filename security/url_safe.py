"""Validação de URLs externas com proteção contra SSRF (Server-Side Request Forgery).

Previne requisições a endereços locais (loopback), redes privadas (RFC1918),
link-local, multicast, ou hosts internos.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def is_ip_safe(ip_str: str) -> bool:
    """Verifica se um endereço IP é público e globalmente roteável."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_global
            and not ip.is_private
            and not ip.is_loopback
            and not ip.is_link_local
            and not ip.is_reserved
            and not ip.is_multicast
            and not ip.is_unspecified
        )
    except ValueError:
        return False


def is_url_ssrf_safe(url: str) -> bool:
    """Verifica se uma URL HTTP/HTTPS resolve apenas para endereços IP públicos e seguros."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False

        addr_info = socket.getaddrinfo(hostname, None)
        if not addr_info:
            return False

        for _family, _socktype, _proto, _canonname, sockaddr in addr_info:
            ip_str = sockaddr[0]
            if not is_ip_safe(ip_str):
                return False

        return True
    except Exception:
        return False
