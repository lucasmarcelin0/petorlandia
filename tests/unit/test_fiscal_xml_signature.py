"""Assinatura XML-DSig dos documentos fiscais no padrão SEFAZ/ABRASF.

O oráculo destes testes não usa o C14N do lxml (que tem um defeito em
sub-árvores no lxml 6.0.2/libxml2 2.14): a forma canônica esperada do nó
assinado e do ``SignedInfo`` é escrita à mão, o digest é recalculado sobre
ela e a SignatureValue é conferida com a chave pública do certificado.
É o mesmo cálculo que a SEFAZ faz ao receber a nota. As assinaturas também
foram conferidas, fora da suíte, com a libxmlsec1.
"""
from __future__ import annotations

import base64
import datetime
import hashlib

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from providers.fiscal.xml_signature import _c14n
from providers.nfe.xml_builder import build_envi_nfe_xml, build_inut_xml
from providers.nfe.xml_signer import sign_event_xml, sign_inutilizacao_xml, sign_nfe_xml
from providers.nfse.betha.xml_signer import sign_betha_xml
from providers.nfse.nacional.xml_signer import sign_nacional_xml


DS = "http://www.w3.org/2000/09/xmldsig#"
NFE = "http://www.portalfiscal.inf.br/nfe"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
CHAVE = "35261012345678000195650010000000011234567891"
URIS = {
    "sha1": (f"{DS}rsa-sha1", f"{DS}sha1", hashlib.sha1, hashes.SHA1),
    "sha256": (
        "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
        "http://www.w3.org/2001/04/xmlenc#sha256",
        hashlib.sha256,
        hashes.SHA256,
    ),
}


@pytest.fixture(scope="module")
def a1():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PET TESTE LTDA:12345678000195")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(
        b"teste", key, cert, None, serialization.BestAvailableEncryption(b"senha-a1")
    )
    return {"pfx": pfx, "password": "senha-a1", "cert": cert}


def _assert_signature(signed_xml: str, *, signed_id: str, expected_canonical: bytes, cert, algoritmo="sha1"):
    """Confere digest e SignatureValue contra formas canônicas escritas à mão."""
    signature_uri, digest_uri, hash_fn, hash_cls = URIS[algoritmo]
    root = etree.fromstring(signed_xml.encode("utf-8"))
    signatures = root.findall(f".//{{{DS}}}Signature")
    assert len(signatures) == 1
    signature = signatures[0]
    assert signature.prefix is None, "a SEFAZ exige Signature sem prefixo ds:"

    target = root.xpath("//*[@Id=$id]", id=signed_id)[0]
    assert signature.getparent() is target.getparent(), "Signature deve ser irmã do nó assinado"
    assert target.getnext() is signature

    digest_value = signature.find(f".//{{{DS}}}DigestValue").text
    assert digest_value == base64.b64encode(hash_fn(expected_canonical).digest()).decode()

    expected_signed_info = (
        f'<SignedInfo xmlns="{DS}">'
        f'<CanonicalizationMethod Algorithm="{C14N}"></CanonicalizationMethod>'
        f'<SignatureMethod Algorithm="{signature_uri}"></SignatureMethod>'
        f'<Reference URI="#{signed_id}">'
        "<Transforms>"
        f'<Transform Algorithm="{DS}enveloped-signature"></Transform>'
        f'<Transform Algorithm="{C14N}"></Transform>'
        "</Transforms>"
        f'<DigestMethod Algorithm="{digest_uri}"></DigestMethod>'
        f"<DigestValue>{digest_value}</DigestValue>"
        "</Reference>"
        "</SignedInfo>"
    ).encode("utf-8")
    signature_value = base64.b64decode(signature.find(f"{{{DS}}}SignatureValue").text)
    cert.public_key().verify(signature_value, expected_signed_info, padding.PKCS1v15(), hash_cls())

    x509_text = signature.find(f".//{{{DS}}}X509Certificate").text
    assert base64.b64decode(x509_text) == cert.public_bytes(serialization.Encoding.DER)
    return root


def _nfe_xml() -> str:
    return (
        f'<NFe xmlns="{NFE}"><infNFe Id="NFe{CHAVE}" versao="4.00">'
        "<ide><cUF>35</cUF><mod>65</mod></ide>"
        "<emit><CNPJ>12345678000195</CNPJ><xNome>Pet Teste</xNome></emit>"
        "</infNFe></NFe>"
    )


CANONICO_INFNFE = (
    f'<infNFe xmlns="{NFE}" Id="NFe{CHAVE}" versao="4.00">'
    "<ide><cUF>35</cUF><mod>65</mod></ide>"
    "<emit><CNPJ>12345678000195</CNPJ><xNome>Pet Teste</xNome></emit>"
    "</infNFe>"
).encode("utf-8")


def test_c14n_de_subarvore_nao_marca_netos_com_xmlns_vazio():
    root = etree.fromstring(_nfe_xml().encode("utf-8"))
    inf = root.find(f"{{{NFE}}}infNFe")
    assert _c14n(inf) == CANONICO_INFNFE


def test_assinatura_nfe_fica_irma_de_infnfe_e_confere(a1):
    signed = sign_nfe_xml(_nfe_xml(), a1["pfx"], a1["password"])
    root = _assert_signature(
        signed, signed_id=f"NFe{CHAVE}", expected_canonical=CANONICO_INFNFE, cert=a1["cert"]
    )
    assert [etree.QName(child).localname for child in root] == ["infNFe", "Signature"]


def test_nfe_assinada_continua_valida_dentro_do_lote(a1):
    signed = sign_nfe_xml(_nfe_xml(), a1["pfx"], a1["password"])
    lote = build_envi_nfe_xml(signed, id_lote=42)
    root = etree.fromstring(lote.encode("utf-8"))
    assert root.tag == f"{{{NFE}}}enviNFe"
    assert root.find(f"{{{NFE}}}indSinc").text == "1"
    assert root.find(f"{{{NFE}}}idLote").text == "42"
    # A forma canônica de infNFe é a mesma dentro do lote (C14N inclusivo).
    _assert_signature(lote, signed_id=f"NFe{CHAVE}", expected_canonical=CANONICO_INFNFE, cert=a1["cert"])


def test_assinatura_do_evento_de_cancelamento(a1):
    evento_id = f"ID110111{CHAVE}01"
    xml = (
        f'<envEvento xmlns="{NFE}" versao="1.00"><idLote>1</idLote><evento versao="1.00">'
        f'<infEvento Id="{evento_id}"><cOrgao>35</cOrgao><tpAmb>2</tpAmb></infEvento>'
        "</evento></envEvento>"
    )
    signed = sign_event_xml(xml, a1["pfx"], a1["password"])
    canonico = (
        f'<infEvento xmlns="{NFE}" Id="{evento_id}"><cOrgao>35</cOrgao><tpAmb>2</tpAmb></infEvento>'
    ).encode("utf-8")
    root = _assert_signature(signed, signed_id=evento_id, expected_canonical=canonico, cert=a1["cert"])
    evento = root.find(f"{{{NFE}}}evento")
    assert [etree.QName(child).localname for child in evento] == ["infEvento", "Signature"]


def test_inutilizacao_monta_id_e_assina(a1):
    xml = build_inut_xml(
        c_uf="35",
        tp_amb="2",
        ano=2026,
        cnpj="12345678000195",
        modelo="65",
        serie=1,
        numero_inicial=10,
        numero_final=12,
        justificativa="Numero pulado por falha no envio",
    )
    inut_id = "ID35" + "26" + "12345678000195" + "65" + "001" + "000000010" + "000000012"
    signed = sign_inutilizacao_xml(xml, a1["pfx"], a1["password"])
    canonico = (
        f'<infInut xmlns="{NFE}" Id="{inut_id}"><tpAmb>2</tpAmb><xServ>INUTILIZAR</xServ>'
        "<cUF>35</cUF><ano>26</ano><CNPJ>12345678000195</CNPJ><mod>65</mod><serie>1</serie>"
        "<nNFIni>10</nNFIni><nNFFin>12</nNFFin><xJust>Numero pulado por falha no envio</xJust></infInut>"
    ).encode("utf-8")
    _assert_signature(signed, signed_id=inut_id, expected_canonical=canonico, cert=a1["cert"])


def test_assinatura_nfse_betha_no_lote(a1):
    xml = (
        '<EnviarLoteRpsEnvio><LoteRps Id="Lote1"><NumeroLote>1</NumeroLote>'
        "<ListaRps><Rps/></ListaRps></LoteRps></EnviarLoteRpsEnvio>"
    )
    signed = sign_betha_xml(xml, a1["pfx"], a1["password"])
    canonico = (
        b'<LoteRps Id="Lote1"><NumeroLote>1</NumeroLote><ListaRps><Rps></Rps></ListaRps></LoteRps>'
    )
    root = _assert_signature(signed, signed_id="Lote1", expected_canonical=canonico, cert=a1["cert"])
    assert [etree.QName(child).localname for child in root] == ["LoteRps", "Signature"]


@pytest.mark.parametrize("algoritmo", ["sha1", "sha256"])
def test_assinatura_dps_nfse_nacional(a1, algoritmo):
    ns = "http://www.sped.fazenda.gov.br/nfse"
    dps_id = "DPS351234567800019500001000000000000001"
    xml = f'<DPS xmlns="{ns}" versao="1.01"><infDPS Id="{dps_id}"><tpAmb>2</tpAmb></infDPS></DPS>'
    signed = sign_nacional_xml(
        xml,
        pfx_bytes=a1["pfx"],
        password=a1["password"],
        signature_algorithm=f"rsa-{algoritmo}",
        digest_algorithm=algoritmo,
    )
    canonico = f'<infDPS xmlns="{ns}" Id="{dps_id}"><tpAmb>2</tpAmb></infDPS>'.encode("utf-8")
    root = _assert_signature(
        signed, signed_id=dps_id, expected_canonical=canonico, cert=a1["cert"], algoritmo=algoritmo
    )
    assert [etree.QName(child).localname for child in root] == ["infDPS", "Signature"]


def test_no_sem_id_e_rejeitado(a1):
    with pytest.raises(ValueError, match="Id"):
        sign_nfe_xml(f'<NFe xmlns="{NFE}"><infNFe versao="4.00"/></NFe>', a1["pfx"], a1["password"])


def test_senha_errada_do_certificado(a1):
    with pytest.raises(ValueError):
        sign_nfe_xml(_nfe_xml(), a1["pfx"], "senha-errada")
