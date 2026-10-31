"""XML signature helper for Sistema Nacional NFS-e layouts."""
from __future__ import annotations

from providers.fiscal.xml_signature import load_pfx, sign_fiscal_xml


def _load_pfx(pfx_bytes: bytes, password: str | None):
    return load_pfx(pfx_bytes, password)


def sign_nacional_xml(
    xml: str,
    *,
    pfx_bytes: bytes,
    password: str | None,
    node_tag: str = "infDPS",
    signature_algorithm: str = "rsa-sha1",
    digest_algorithm: str = "sha1",
) -> str:
    """Assina ``infDPS`` (ou ``infPedReg``); a ``Signature`` fica no nó pai."""
    return sign_fiscal_xml(
        xml,
        pfx_bytes=pfx_bytes,
        password=password,
        node_tag=node_tag,
        signature_algorithm=signature_algorithm,
        digest_algorithm=digest_algorithm,
    )
