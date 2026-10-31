"""Cliente dos web services NF-e/NFC-e 4.00 da SEFAZ-SP (SOAP 1.2).

O transporte é montado à mão (``providers.fiscal.sefaz_soap``): o XML
assinado vai dentro de ``nfeDadosMsg`` exatamente como foi assinado, sem
baixar o WSDL a cada chamada. A interface pública (métodos e
``SefazSoapResponse``) é a mesma do cliente anterior baseado em Zeep.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import logging
import os
import tempfile
from typing import Any, Iterator, Optional

from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, pkcs12
from lxml import etree

from providers.fiscal.sefaz_soap import SoapResult, post_soap12
from security.xml_safe import safe_lxml_fromstring


logger = logging.getLogger(__name__)

NFE_NS = "http://www.portalfiscal.inf.br/nfe"

# serviço -> (nome do web service 4.00, operação SOAP)
SERVICOS = {
    "autorizacao": ("NFeAutorizacao4", "nfeAutorizacaoLote"),
    "ret_autorizacao": ("NFeRetAutorizacao4", "nfeRetAutorizacaoLote"),
    "recepcao_evento": ("NFeRecepcaoEvento4", "nfeRecepcaoEvento"),
    "status_servico": ("NFeStatusServico4", "nfeStatusServicoNF"),
    "consulta_protocolo": ("NFeConsultaProtocolo4", "nfeConsultaNF"),
    "inutilizacao": ("NFeInutilizacao4", "nfeInutilizacaoNF"),
}


@dataclass
class SefazSoapResponse:
    success: bool
    response: Any | None
    request_xml: str | None
    response_xml: str | None
    error_message: str | None = None


@dataclass
class SefazWsdlConfig:
    autorizacao: str
    ret_autorizacao: str
    recepcao_evento: str
    status_servico: str = ""
    consulta_protocolo: str = ""
    inutilizacao: str = ""
    tp_amb: str = "2"


def _normalize_env(env: str | None) -> str:
    env_normalized = (env or "homolog").lower()
    if env_normalized not in {"homolog", "prod"}:
        raise ValueError("NFE_ENV deve ser homolog ou prod.")
    return env_normalized


def get_sefaz_sp_wsdl_config(env: str) -> SefazWsdlConfig:
    """Endereços NF-e (modelo 55) da SEFAZ-SP."""
    env_normalized = _normalize_env(env)
    base = (
        "https://homologacao.nfe.fazenda.sp.gov.br/ws"
        if env_normalized == "homolog"
        else "https://nfe.fazenda.sp.gov.br/ws"
    )
    return SefazWsdlConfig(
        autorizacao=f"{base}/nfeautorizacao4.asmx?wsdl",
        ret_autorizacao=f"{base}/nferetautorizacao4.asmx?wsdl",
        recepcao_evento=f"{base}/nferecepcaoevento4.asmx?wsdl",
        status_servico=f"{base}/nfestatusservico4.asmx?wsdl",
        consulta_protocolo=f"{base}/nfeconsultaprotocolo4.asmx?wsdl",
        inutilizacao=f"{base}/nfeinutilizacao4.asmx?wsdl",
        tp_amb="2" if env_normalized == "homolog" else "1",
    )


def get_sefaz_sp_nfce_config(env: str) -> SefazWsdlConfig:
    """Endereços NFC-e (modelo 65) da SEFAZ-SP, publicados no portal da NFC-e."""
    env_normalized = _normalize_env(env)
    base = (
        "https://homologacao.nfce.fazenda.sp.gov.br/ws"
        if env_normalized == "homolog"
        else "https://nfce.fazenda.sp.gov.br/ws"
    )
    return SefazWsdlConfig(
        autorizacao=f"{base}/NFeAutorizacao4.asmx",
        ret_autorizacao=f"{base}/NFeRetAutorizacao4.asmx",
        recepcao_evento=f"{base}/NFeRecepcaoEvento4.asmx",
        status_servico=f"{base}/NFeStatusServico4.asmx",
        consulta_protocolo=f"{base}/NFeConsultaProtocolo4.asmx",
        inutilizacao=f"{base}/NFeInutilizacao4.asmx",
        tp_amb="2" if env_normalized == "homolog" else "1",
    )


def _endpoint(url: str) -> str:
    return url.split("?", 1)[0]


class SefazSpNfeClient:
    def __init__(
        self,
        wsdl_config: SefazWsdlConfig,
        pfx_bytes: Optional[bytes] = None,
        pfx_password: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.wsdl_config = wsdl_config
        self.pfx_bytes = pfx_bytes
        self.pfx_password = pfx_password
        self.timeout = timeout

    @contextmanager
    def _cert_files(self) -> Iterator[tuple[str, str] | None]:
        cert_files = None
        if self.pfx_bytes:
            cert_files = _pfx_to_temp_pem(self.pfx_bytes, self.pfx_password)
        try:
            yield cert_files
        finally:
            if cert_files:
                _cleanup_cert_files(cert_files)

    def _call(self, servico: str, xml: str) -> SefazSoapResponse:
        url = getattr(self.wsdl_config, servico, "")
        if not url:
            return SefazSoapResponse(False, None, None, None, f"Endereço do serviço {servico} não configurado.")
        service, operation = SERVICOS[servico]
        with self._cert_files() as cert_files:
            result: SoapResult = post_soap12(
                _endpoint(url),
                service,
                operation,
                xml,
                cert_files=cert_files,
                timeout=self.timeout,
            )
        return SefazSoapResponse(
            result.ok,
            result.body_xml,
            result.request_xml,
            result.response_xml,
            error_message=result.error_message,
        )

    def autorizacao(self, xml_lote: str) -> SefazSoapResponse:
        """Envia um ``enviNFe`` (lote) já com a NF-e assinada."""
        return self._call("autorizacao", xml_lote)

    def ret_autorizacao(self, recibo: str) -> SefazSoapResponse:
        """Consulta o recibo de um lote assíncrono (``consReciNFe``)."""
        return self._call("ret_autorizacao", recibo)

    def recepcao_evento(self, xml_evento_assinado: str) -> SefazSoapResponse:
        return self._call("recepcao_evento", xml_evento_assinado)

    def evento_cancelamento(self, chave: str, xml_evento_assinado: str) -> SefazSoapResponse:
        return self.recepcao_evento(xml_evento_assinado)

    def status_servico(self, xml: str) -> SefazSoapResponse:
        return self._call("status_servico", xml)

    def consulta_protocolo(self, xml: str) -> SefazSoapResponse:
        return self._call("consulta_protocolo", xml)

    def inutilizacao(self, xml_assinado: str) -> SefazSoapResponse:
        return self._call("inutilizacao", xml_assinado)

    def test_connection(self, c_uf: str = "35") -> SefazSoapResponse:
        """Consulta o status do serviço com o certificado da empresa.

        Valida rede, TLS e aceitação do certificado pela SEFAZ. Sucesso só
        com ``cStat`` 107 (serviço em operação).
        """
        response = self.status_servico(build_cons_stat_serv_xml(self.wsdl_config.tp_amb, c_uf))
        if not response.success:
            return response
        c_stat = _find_text(response.response, "cStat")
        if c_stat != "107":
            motivo = _find_text(response.response, "xMotivo") or "sem motivo informado"
            return SefazSoapResponse(
                False,
                response.response,
                response.request_xml,
                response.response_xml,
                error_message=f"SEFAZ retornou {c_stat}: {motivo}",
            )
        return response


def build_cons_stat_serv_xml(tp_amb: str, c_uf: str = "35") -> str:
    root = etree.Element("consStatServ", nsmap={None: NFE_NS})
    root.set("versao", "4.00")
    etree.SubElement(root, "tpAmb").text = str(tp_amb)
    etree.SubElement(root, "cUF").text = str(c_uf)
    etree.SubElement(root, "xServ").text = "STATUS"
    return etree.tostring(root, encoding="unicode")


def _find_text(xml: str | None, tag: str) -> str | None:
    if not xml:
        return None
    try:
        root = safe_lxml_fromstring(xml.encode("utf-8"))
    except Exception:  # noqa: BLE001 - retorno não-XML: não há o que extrair
        return None
    node = root.find(f".//{{*}}{tag}")
    if node is None and root.tag.split("}", 1)[-1] == tag:
        node = root
    return node.text if node is not None else None


def _pfx_to_temp_pem(pfx_bytes: bytes, password: str | None) -> tuple[str, str]:
    password_bytes = password.encode("utf-8") if password else None
    private_key, certificate, additional = pkcs12.load_key_and_certificates(
        pfx_bytes,
        password_bytes,
    )
    if private_key is None or certificate is None:
        raise ValueError("Certificado A1 inválido para conexão TLS.")

    key_pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    cert_chain = [certificate] + list(additional or [])
    cert_pem = b"".join(cert.public_bytes(Encoding.PEM) for cert in cert_chain)

    cert_file = tempfile.NamedTemporaryFile(delete=False)
    key_file = tempfile.NamedTemporaryFile(delete=False)
    cert_file.write(cert_pem)
    key_file.write(key_pem)
    cert_file.flush()
    key_file.flush()
    cert_file.close()
    key_file.close()
    return cert_file.name, key_file.name


def _cleanup_cert_files(cert_files: tuple[str, str]) -> None:
    for path in cert_files:
        try:
            os.unlink(path)
        except FileNotFoundError:
            continue
