"""Assinatura XML NF-e/NFC-e (modelos 55 e 65) e de seus eventos."""
from __future__ import annotations

from dataclasses import dataclass

from providers.fiscal.xml_signature import load_pfx, sign_fiscal_xml


@dataclass
class SignedXmlResult:
    xml: str
    signature_id: str


def _load_pfx(pfx_bytes: bytes, password: str | None):
    return load_pfx(pfx_bytes, password)


def sign_nfe_xml(xml: str, pfx_bytes: bytes, password: str | None) -> str:
    """Assina ``infNFe``; a ``Signature`` fica dentro de ``NFe``, após ``infNFe``."""
    return sign_fiscal_xml(xml, pfx_bytes=pfx_bytes, password=password, node_tag="infNFe")


def sign_event_xml(xml: str, pfx_bytes: bytes, password: str | None) -> str:
    """Assina ``infEvento``; a ``Signature`` fica dentro de ``evento``."""
    return sign_fiscal_xml(xml, pfx_bytes=pfx_bytes, password=password, node_tag="infEvento")


def sign_inutilizacao_xml(xml: str, pfx_bytes: bytes, password: str | None) -> str:
    """Assina ``infInut``; a ``Signature`` fica dentro de ``inutNFe``."""
    return sign_fiscal_xml(xml, pfx_bytes=pfx_bytes, password=password, node_tag="infInut")
