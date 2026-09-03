"""Fetch de URLs externas com proteção contra SSRF e DNS rebinding."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
import ssl
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

import certifi
from flask import current_app, has_app_context
from urllib3 import HTTPConnectionPool, HTTPSConnectionPool, Timeout
from urllib3.exceptions import HTTPError


TEST_DOMAINS_SUFFIXES = (
    ".example",
    ".test",
    ".local",
    ".localhost",
    "example.com",
    "example.org",
    "example.net",
)
_ALLOWED_SCHEMES = ("http", "https")
_ALLOWED_PORTS = {80, 443}


class UnsafeExternalURL(ValueError):
    """A URL aponta para um destino que o servidor não pode acessar."""


class ExternalFetchError(RuntimeError):
    """A URL era permitida, mas não pôde ser obtida com segurança."""


class ExternalResponseTooLarge(ExternalFetchError):
    """A resposta externa ultrapassou o limite configurado."""


@dataclass(frozen=True)
class SafeURLResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes


def _is_ip_safe(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip_obj.is_global
        and not ip_obj.is_private
        and not ip_obj.is_loopback
        and not ip_obj.is_link_local
        and not ip_obj.is_multicast
        and not ip_obj.is_reserved
        and not ip_obj.is_unspecified
    )


def _parse_url(url: str, allowed_schemes: tuple[str, ...] = _ALLOWED_SCHEMES):
    if not isinstance(url, str) or not url.strip():
        raise UnsafeExternalURL("URL ausente")
    if any(ord(char) < 32 for char in url):
        raise UnsafeExternalURL("URL contém caracteres de controle")

    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise UnsafeExternalURL("URL inválida") from exc

    scheme = (parsed.scheme or "").lower()
    hostname = (parsed.hostname or "").strip("[]").rstrip(".").lower()
    if scheme not in allowed_schemes or not hostname:
        raise UnsafeExternalURL("Esquema ou domínio não permitido")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeExternalURL("Credenciais embutidas não são permitidas")

    port = port or (443 if scheme == "https" else 80)
    if port not in _ALLOWED_PORTS:
        raise UnsafeExternalURL("Porta externa não permitida")
    return parsed, hostname, port


def _resolve_public_ips(hostname: str, port: int) -> list[str]:
    try:
        direct_ip = ipaddress.ip_address(hostname)
    except ValueError:
        direct_ip = None

    if direct_ip is not None:
        if not _is_ip_safe(direct_ip):
            raise UnsafeExternalURL("Endereço IP privado ou reservado")
        return [str(direct_ip)]

    try:
        addr_info = socket.getaddrinfo(
            hostname,
            port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
    except (socket.gaierror, socket.error) as exc:
        raise UnsafeExternalURL("Domínio não pôde ser resolvido") from exc

    addresses: list[str] = []
    for _family, _socktype, _proto, _canonname, sockaddr in addr_info:
        ip_text = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_text)
        except ValueError as exc:
            raise UnsafeExternalURL("DNS retornou endereço inválido") from exc
        if not _is_ip_safe(ip_obj):
            raise UnsafeExternalURL("DNS retornou endereço privado ou reservado")
        normalized = str(ip_obj)
        if normalized not in addresses:
            addresses.append(normalized)

    if not addresses:
        raise UnsafeExternalURL("DNS não retornou endereços")
    return addresses


def _is_testing_domain(hostname: str) -> bool:
    if not (has_app_context() and current_app.config.get("TESTING")):
        return False
    return any(
        hostname == suffix.lstrip(".") or hostname.endswith(suffix)
        for suffix in TEST_DOMAINS_SUFFIXES
    )


def is_url_ssrf_safe(
    url: str,
    allowed_schemes: tuple[str, ...] = _ALLOWED_SCHEMES,
) -> bool:
    """Retorna ``True`` somente para URLs HTTP(S) que resolvem a IPs públicos."""
    try:
        _parsed, hostname, port = _parse_url(url, allowed_schemes)
        _resolve_public_ips(hostname, port)
        return True
    except UnsafeExternalURL:
        # Domínios sintéticos são aceitos apenas por testes que substituem o
        # transporte; nunca liberamos esse atalho em produção.
        try:
            _parsed, hostname, _port = _parse_url(url, allowed_schemes)
        except UnsafeExternalURL:
            return False
        return _is_testing_domain(hostname)


def safe_fetch_url(
    url: str,
    *,
    timeout: float = 10,
    max_bytes: int = 10 * 1024 * 1024,
    user_agent: str = "PetOrlandia/1.0",
) -> SafeURLResponse:
    """Obtém uma URL sem redirecionar e conecta ao IP já validado.

    O domínio é resolvido uma única vez. A conexão usa diretamente um dos IPs
    públicos retornados, mas mantém ``Host``, SNI e validação do certificado
    contra o domínio original. Isso fecha a janela de DNS rebinding existente
    quando se valida o DNS e depois se chama um cliente que o resolve novamente.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes deve ser positivo")

    parsed, hostname, port = _parse_url(url)
    addresses = _resolve_public_ips(hostname, port)
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    host_header = display_host if port == default_port else f"{display_host}:{port}"
    request_headers = {
        "Host": host_header,
        "User-Agent": user_agent,
        "Accept-Encoding": "identity",
    }
    request_timeout = Timeout(connect=timeout, read=timeout)
    last_error: Exception | None = None

    for address in addresses:
        pool = None
        response = None
        try:
            if parsed.scheme.lower() == "https":
                pool = HTTPSConnectionPool(
                    address,
                    port=port,
                    timeout=request_timeout,
                    retries=False,
                    maxsize=1,
                    block=True,
                    cert_reqs=ssl.CERT_REQUIRED,
                    ca_certs=certifi.where(),
                    assert_hostname=hostname,
                    server_hostname=hostname,
                )
            else:
                pool = HTTPConnectionPool(
                    address,
                    port=port,
                    timeout=request_timeout,
                    retries=False,
                    maxsize=1,
                    block=True,
                )

            response = pool.urlopen(
                "GET",
                target,
                headers=request_headers,
                redirect=False,
                preload_content=False,
            )
            status_code = int(response.status)
            if 300 <= status_code < 400:
                raise UnsafeExternalURL("Redirecionamentos externos não são permitidos")
            if status_code >= 400:
                raise ExternalFetchError(f"Servidor externo respondeu HTTP {status_code}")

            declared_size = response.headers.get("Content-Length")
            if declared_size:
                try:
                    if int(declared_size) > max_bytes:
                        raise ExternalResponseTooLarge("Resposta externa excede o limite")
                except ValueError:
                    pass

            content = response.read(max_bytes + 1, decode_content=True)
            if len(content) > max_bytes:
                raise ExternalResponseTooLarge("Resposta externa excede o limite")
            return SafeURLResponse(status_code, dict(response.headers), content)
        except UnsafeExternalURL:
            raise
        except ExternalFetchError:
            raise
        except (HTTPError, OSError, TimeoutError) as exc:
            last_error = exc
        finally:
            if response is not None:
                response.release_conn()
            if pool is not None:
                pool.close()

    raise ExternalFetchError("Não foi possível acessar o destino externo") from last_error
