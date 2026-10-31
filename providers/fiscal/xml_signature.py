"""Assinatura XML-DSig no padrão dos documentos fiscais (NF-e, NFC-e, NFS-e).

Por que este módulo existe:
    Os assinadores antigos usavam a API da signxml 2.x. Com a signxml 4.x
    (fixada em ``requirements.txt``) eles quebravam no construtor do
    ``XMLSigner`` antes de assinar qualquer nota: o método de construção
    deixou de aceitar a string ``"enveloped"`` e SHA-1 passou a ser
    recusado. Além disso, com o namespace xmldsig como padrão (exigência da
    SEFAZ), a signxml 4.x calcula a SignatureValue sobre elementos sem
    namespace e a assinatura não confere depois de serializada.

    O perfil fiscal é fixo e pequeno, então a assinatura é feita aqui com
    lxml (C14N) e cryptography (RSA), sem depender dessas variações.

Perfil seguido (MOC NF-e 4.00, item 4.2, e ABRASF):
    - assinatura *enveloped*, com ``<Signature>`` IRMÃ do nó assinado
      (ex.: ``NFe > infNFe + Signature``);
    - ``Reference URI="#<Id do nó>"``;
    - transforms ``enveloped-signature`` + C14N 1.0
      (``REC-xml-c14n-20010315``), também usado no ``SignedInfo``;
    - ``<Signature>`` no namespace padrão do xmldsig, sem prefixo ``ds:``;
    - ``X509Data`` apenas com o certificado do titular.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from lxml import etree

# O XML assinado é montado localmente, mas pode ter passado por concatenação
# de strings ou cache; o parser endurecido cobre entidades indevidas.
from security.xml_safe import safe_lxml_fromstring


DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
C14N_10 = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
ENVELOPED = f"{DSIG_NS}enveloped-signature"

_DIGESTS = {
    "sha1": (hashlib.sha1, f"{DSIG_NS}sha1"),
    "sha256": (hashlib.sha256, "http://www.w3.org/2001/04/xmlenc#sha256"),
}
_SIGNATURES = {
    "rsa-sha1": (hashes.SHA1, f"{DSIG_NS}rsa-sha1"),
    "rsa-sha256": (hashes.SHA256, "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"),
}


def load_pfx(pfx_bytes: bytes, password: str | None) -> tuple[Any, Any]:
    """Carrega chave privada e certificado de um A1 (PKCS#12)."""
    password_bytes = password.encode("utf-8") if password else None
    private_key, certificate, _additional = pkcs12.load_key_and_certificates(
        pfx_bytes,
        password_bytes,
    )
    if certificate is None or private_key is None:
        raise ValueError("Certificado A1 inválido para assinatura XML.")
    return private_key, certificate


def _local_name(element: etree._Element) -> str:
    return str(element.tag).split("}", 1)[-1]


def _find_by_local_name(root: etree._Element, node_tag: str) -> etree._Element | None:
    for candidate in root.iter():
        if isinstance(candidate.tag, str) and _local_name(candidate) == node_tag:
            return candidate
    return None


def _c14n(element: etree._Element) -> bytes:
    """C14N 1.0 inclusivo do nó, como a SEFAZ calcula.

    Não usa ``etree.tostring(no, method="c14n")`` direto: no lxml 6.0.2 /
    libxml2 2.14 o C14N de uma sub-árvore cujo namespace padrão vem de um
    ancestral marca netos com ``xmlns=""`` (ex.: ``<cUF xmlns="">``), o que
    muda o digest e invalida a assinatura. O nó é copiado para um documento
    próprio, levando todos os namespaces em escopo (o C14N inclusivo os
    exige no elemento apex), e só então canonicalizado.
    """
    standalone = etree.fromstring(etree.tostring(element))
    missing = {
        prefix: uri
        for prefix, uri in element.nsmap.items()
        if standalone.nsmap.get(prefix) != uri
    }
    if missing:
        apex = etree.Element(
            standalone.tag,
            attrib=dict(standalone.attrib),
            nsmap={**element.nsmap, **standalone.nsmap},
        )
        apex.text = standalone.text
        for child in list(standalone):
            apex.append(child)
        standalone = etree.fromstring(etree.tostring(apex))
    return etree.tostring(standalone, method="c14n", exclusive=False, with_comments=False)


def _ds(parent: etree._Element, tag: str, **attrib: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{DSIG_NS}}}{tag}", **attrib)


def sign_fiscal_xml(
    xml: str | bytes,
    *,
    pfx_bytes: bytes,
    password: str | None,
    node_tag: str,
    signature_algorithm: str = "rsa-sha1",
    digest_algorithm: str = "sha1",
) -> str:
    """Assina o primeiro nó ``node_tag`` e devolve o XML completo assinado.

    A ``<Signature>`` entra como último filho do PAI do nó assinado, logo,
    irmã dele. Se o nó assinado for a raiz, ela entra dentro da raiz (o
    transform enveloped-signature a exclui do digest).
    """
    if digest_algorithm not in _DIGESTS:
        raise ValueError(f"Algoritmo de digest não suportado: {digest_algorithm}")
    if signature_algorithm not in _SIGNATURES:
        raise ValueError(f"Algoritmo de assinatura não suportado: {signature_algorithm}")

    private_key, certificate = load_pfx(pfx_bytes, password)
    root = safe_lxml_fromstring(xml)
    target = _find_by_local_name(root, node_tag)
    if target is None:
        raise ValueError(f"Nó {node_tag} não encontrado para assinatura.")
    signature_id = target.get("Id")
    if not signature_id:
        raise ValueError(f"Nó {node_tag} não possui atributo Id para assinatura.")

    container = target.getparent()
    if container is None:
        container = target

    # Digest do nó, calculado antes de a Signature existir no documento.
    hash_function, digest_uri = _DIGESTS[digest_algorithm]
    digest_value = base64.b64encode(hash_function(_c14n(target)).digest()).decode("ascii")

    signature = etree.SubElement(container, f"{{{DSIG_NS}}}Signature", nsmap={None: DSIG_NS})
    signed_info = _ds(signature, "SignedInfo")
    hash_class, signature_uri = _SIGNATURES[signature_algorithm]
    _ds(signed_info, "CanonicalizationMethod", Algorithm=C14N_10)
    _ds(signed_info, "SignatureMethod", Algorithm=signature_uri)
    reference = _ds(signed_info, "Reference", URI=f"#{signature_id}")
    transforms = _ds(reference, "Transforms")
    _ds(transforms, "Transform", Algorithm=ENVELOPED)
    _ds(transforms, "Transform", Algorithm=C14N_10)
    _ds(reference, "DigestMethod", Algorithm=digest_uri)
    _ds(reference, "DigestValue").text = digest_value

    # SignedInfo canonicalizado já dentro do documento: é o que a SEFAZ confere.
    signature_value = private_key.sign(_c14n(signed_info), padding.PKCS1v15(), hash_class())
    _ds(signature, "SignatureValue").text = base64.b64encode(signature_value).decode("ascii")
    key_info = _ds(signature, "KeyInfo")
    x509_data = _ds(key_info, "X509Data")
    _ds(x509_data, "X509Certificate").text = base64.b64encode(
        certificate.public_bytes(Encoding.DER)
    ).decode("ascii")

    return etree.tostring(root, encoding="unicode")
