import gzip
import base64

from providers.nfse.nacional.client import NacionalNfseClient, NacionalNfseConfig


class _FakeResponse:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = "{}"

    def json(self):
        return self._payload


def _gzip_b64(text: str) -> str:
    return base64.b64encode(gzip.compress(text.encode("utf-8"))).decode("ascii")


def test_parse_response_extrai_xml_e_chave():
    chave = "1" * 50
    xml = (
        f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">'
        f'<infNFSe Id="NFS{chave}"><nNFSe>123</nNFSe><cVerif>ABC123</cVerif></infNFSe>'
        f"</NFSe>"
    )
    response = _FakeResponse(
        {
            "chaveAcesso": chave,
            "nfseXmlGZipB64": _gzip_b64(xml),
        }
    )

    parsed = NacionalNfseClient(NacionalNfseConfig())._parse_response(response)

    assert parsed.success is True
    assert parsed.access_key == chave
    assert parsed.nfse_number == "123"
    assert parsed.verification_code == "ABC123"
    assert parsed.response_xml == xml
