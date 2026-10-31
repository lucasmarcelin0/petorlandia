"""Transporte SOAP 1.2 para os web services da SEFAZ (NF-e/NFC-e 4.00).

Os serviços 4.00 recebem o XML do documento dentro de ``nfeDadosMsg`` e
devolvem o resultado dentro de ``nfeResultMsg``. Montar o envelope à mão
evita baixar o WSDL a cada chamada e garante que o XML assinado vá como
XML (e não como texto escapado), sem reserializar o conteúdo assinado.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
from typing import Any, Optional

from lxml import etree
import requests

from security.xml_safe import safe_lxml_fromstring


logger = logging.getLogger(__name__)

SOAP12_NS = "http://www.w3.org/2003/05/soap-envelope"
WSDL_BASE_NS = "http://www.portalfiscal.inf.br/nfe/wsdl"

_XML_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>\s*")


@dataclass
class SoapResult:
    ok: bool
    http_status: Optional[int]
    request_xml: str
    response_xml: Optional[str]
    body_xml: Optional[str]
    error_message: Optional[str] = None


def service_namespace(service: str) -> str:
    return f"{WSDL_BASE_NS}/{service}"


def strip_xml_declaration(xml: str) -> str:
    return _XML_DECLARATION.sub("", xml or "", count=1)


def build_soap12_envelope(service: str, body_xml: str, operation_wrapper: str | None = None) -> str:
    """Envelope SOAP 1.2 com o XML do documento dentro de ``nfeDadosMsg``.

    ``operation_wrapper``: serviços como a Distribuição DF-e põem o
    ``nfeDadosMsg`` dentro do elemento da operação (``nfeDistDFeInteresse``).
    """
    dados = strip_xml_declaration(body_xml)
    if operation_wrapper:
        corpo = (
            f'<{operation_wrapper} xmlns="{service_namespace(service)}">'
            f"<nfeDadosMsg>{dados}</nfeDadosMsg>"
            f"</{operation_wrapper}>"
        )
    else:
        corpo = f'<nfeDadosMsg xmlns="{service_namespace(service)}">{dados}</nfeDadosMsg>'
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        f'xmlns:soap12="{SOAP12_NS}">'
        f"<soap12:Body>{corpo}</soap12:Body>"
        "</soap12:Envelope>"
    )


def extract_result_body(
    response_xml: str | None, result_tags: tuple[str, ...] = ("nfeResultMsg",)
) -> tuple[Optional[str], Optional[str]]:
    """Devolve (XML do retorno dentro de ``nfeResultMsg``, mensagem de Fault)."""
    if not response_xml:
        return None, None
    try:
        root = safe_lxml_fromstring(response_xml.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - resposta não-XML (HTML de erro, proxy)
        return None, f"Resposta da SEFAZ não é XML válido: {exc}"

    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        local = node.tag.split("}", 1)[-1]
        if local in result_tags:
            children = [child for child in node if isinstance(child.tag, str)]
            if children:
                return etree.tostring(children[0], encoding="unicode"), None
            return None, f"Resposta da SEFAZ sem conteúdo em {local}."
        if local == "Fault":
            texts = [
                (item.text or "").strip()
                for item in node.iter()
                if isinstance(item.tag, str)
                and item.tag.split("}", 1)[-1] in {"Text", "faultstring"}
                and (item.text or "").strip()
            ]
            return None, "; ".join(texts) or "SOAP Fault sem descrição."
    return None, "Resposta da SEFAZ sem nfeResultMsg."


def _tls_verify() -> Any:
    """Bundle de CAs para validar o servidor da SEFAZ.

    Padrão: CAs do ``certifi``. Se a SEFAZ usar cadeia ICP-Brasil fora do
    bundle público, aponte ``SEFAZ_CA_BUNDLE`` para um arquivo PEM com a
    cadeia. A validação TLS nunca é desligada aqui.
    """
    bundle = (os.getenv("SEFAZ_CA_BUNDLE") or "").strip()
    return bundle or True


def post_soap12(
    url: str,
    service: str,
    operation: str,
    body_xml: str,
    *,
    cert_files: tuple[str, str] | None,
    timeout: int = 30,
    session: Optional[requests.Session] = None,
    operation_wrapper: str | None = None,
    result_tags: tuple[str, ...] = ("nfeResultMsg",),
) -> SoapResult:
    """Envia ``body_xml`` ao serviço SOAP 1.2 da SEFAZ e extrai o retorno."""
    envelope = build_soap12_envelope(service, body_xml, operation_wrapper)
    headers = {
        "Content-Type": (
            'application/soap+xml; charset=utf-8; '
            f'action="{service_namespace(service)}/{operation}"'
        ),
    }
    http = session or requests
    try:
        response = http.post(
            url,
            data=envelope.encode("utf-8"),
            headers=headers,
            cert=cert_files,
            timeout=timeout,
            verify=_tls_verify(),
        )
    except requests.RequestException as exc:
        # Rede, TLS ou timeout: não é bug nosso, mas precisa de rastro.
        logger.warning("Falha de transporte com a SEFAZ em %s (%s): %s", service, url, exc)
        return SoapResult(False, None, envelope, None, None, str(exc))

    response.encoding = response.encoding or "utf-8"
    response_xml = response.text
    body_xml, fault = extract_result_body(response_xml, result_tags)
    if response.status_code >= 400 or body_xml is None:
        message = fault or f"SEFAZ respondeu HTTP {response.status_code}."
        logger.warning("SEFAZ %s respondeu %s: %s", service, response.status_code, message)
        return SoapResult(False, response.status_code, envelope, response_xml, body_xml, message)
    return SoapResult(True, response.status_code, envelope, response_xml, body_xml, None)
