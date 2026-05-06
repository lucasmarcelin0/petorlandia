"""XML signature helper for Sistema Nacional NFS-e layouts."""
from __future__ import annotations

from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree
from signxml import XMLSigner

from security.xml_safe import safe_lxml_fromstring


def _load_pfx(pfx_bytes: bytes, password: str | None):
    password_bytes = password.encode("utf-8") if password else None
    private_key, certificate, _additional = pkcs12.load_key_and_certificates(
        pfx_bytes,
        password_bytes,
    )
    if certificate is None or private_key is None:
        raise ValueError("Certificado A1 invalido para assinatura XML.")
    return private_key, certificate


def sign_nacional_xml(
    xml: str,
    *,
    pfx_bytes: bytes,
    password: str | None,
    node_tag: str = "infDPS",
    signature_algorithm: str = "rsa-sha1",
    digest_algorithm: str = "sha1",
) -> str:
    private_key, certificate = _load_pfx(pfx_bytes, password)
    root = safe_lxml_fromstring(xml)
    target = None
    for candidate in root.iter():
        local_name = str(candidate.tag).split("}", 1)[-1]
        if local_name == node_tag:
            target = candidate
            break
    if target is None:
        raise ValueError(f"No {node_tag} nao encontrado para assinatura.")
    signature_id = target.get("Id")
    if not signature_id:
        raise ValueError(f"No {node_tag} nao possui atributo Id para assinatura.")

    signer = XMLSigner(
        method="enveloped",
        signature_algorithm=signature_algorithm,
        digest_algorithm=digest_algorithm,
    )
    signed_node = signer.sign(
        target,
        key=private_key,
        cert=certificate,
        reference_uri=f"#{signature_id}",
    )
    parent = target.getparent()
    if parent is None:
        return etree.tostring(signed_node, encoding="unicode")
    parent.replace(target, signed_node)
    return etree.tostring(root, encoding="unicode")
