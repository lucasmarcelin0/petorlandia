"""Assinatura XML para NFS-e Betha (ABRASF)."""
from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from providers.fiscal.xml_signature import load_pfx, sign_fiscal_xml


@dataclass
class SignedXmlResult:
    xml: str
    signature_id: str


def _load_pfx(pfx_bytes: bytes, password: str | None):
    return load_pfx(pfx_bytes, password)


def _sign_node(xml_root: etree._Element, node_tag: str) -> SignedXmlResult:
    target = xml_root.find(f".//{node_tag}")
    if target is None:
        raise ValueError(f"Nó {node_tag} não encontrado para assinatura.")
    signature_id = target.get("Id")
    if not signature_id:
        raise ValueError(f"Nó {node_tag} não possui atributo Id para assinatura.")
    return SignedXmlResult(xml=etree.tostring(xml_root, encoding="unicode"), signature_id=signature_id)


def sign_betha_xml(xml: str, pfx_bytes: bytes, password: str | None, node_tag: str = "LoteRps") -> str:
    """Assina o nó ``node_tag`` (padrão ``LoteRps``) no modelo ABRASF.

    A ``Signature`` fica após o nó assinado, dentro do mesmo pai
    (``EnviarLoteRpsEnvio > LoteRps + Signature``).
    """
    return sign_fiscal_xml(xml, pfx_bytes=pfx_bytes, password=password, node_tag=node_tag)
