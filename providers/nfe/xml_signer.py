"""Assinatura XML NF-e (modelo 55)."""
from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree
from signxml import XMLSigner


@dataclass
class SignedXmlResult:
    xml: str
    signature_id: str


def _load_pfx(pfx_bytes: bytes, password: str | None):
    password_bytes = password.encode("utf-8") if password else None
    private_key, certificate, _additional = pkcs12.load_key_and_certificates(
        pfx_bytes,
        password_bytes,
    )
    if certificate is None or private_key is None:
        raise ValueError("Certificado A1 inválido para assinatura XML.")
    return private_key, certificate


def sign_nfe_xml(xml: str, pfx_bytes: bytes, password: str | None) -> str:
    return _sign_xml_node(xml, pfx_bytes, password, "infNFe")


def sign_event_xml(xml: str, pfx_bytes: bytes, password: str | None) -> str:
    return _sign_xml_node(xml, pfx_bytes, password, "infEvento")


def _sign_xml_node(xml: str, pfx_bytes: bytes, password: str | None, node_tag: str) -> str:
    private_key, certificate = _load_pfx(pfx_bytes, password)
    xml_root = etree.fromstring(xml.encode("utf-8"))
    signature_target = xml_root.find(f".//{{http://www.portalfiscal.inf.br/nfe}}{node_tag}")
    if signature_target is None:
        signature_target = xml_root.find(f".//{node_tag}")
    if signature_target is None:
        raise ValueError(f"Nó {node_tag} não encontrado para assinatura.")

    signature_id = signature_target.get("Id")
    if not signature_id:
        raise ValueError(f"Nó {node_tag} não possui atributo Id para assinatura.")

    signer = XMLSigner(
        method="enveloped",
        signature_algorithm="rsa-sha1",
        digest_algorithm="sha1",
    )
    signed_node = signer.sign(
        signature_target,
        key=private_key,
        cert=certificate,
        reference_uri=f"#{signature_id}",
    )

    parent = signature_target.getparent()
    if parent is None:
        return etree.tostring(signed_node, encoding="unicode")

    parent.replace(signature_target, signed_node)
    return etree.tostring(xml_root, encoding="unicode")
