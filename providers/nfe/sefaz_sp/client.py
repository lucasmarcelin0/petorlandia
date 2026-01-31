"""Cliente SOAP NF-e SEFAZ SP usando Zeep."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
import tempfile
from typing import Any, Optional

from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, pkcs12
from zeep import Client, Settings
from zeep.exceptions import Fault
from zeep.plugins import HistoryPlugin
from zeep.transports import Transport
import requests


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


def get_sefaz_sp_wsdl_config(env: str) -> SefazWsdlConfig:
    env_normalized = (env or "homolog").lower()
    if env_normalized not in {"homolog", "prod"}:
        raise ValueError("NFE_ENV deve ser homolog ou prod.")

    base = (
        "https://homologacao.nfe.fazenda.sp.gov.br/ws"
        if env_normalized == "homolog"
        else "https://nfe.fazenda.sp.gov.br/ws"
    )
    return SefazWsdlConfig(
        autorizacao=f"{base}/nfeautorizacao4.asmx?wsdl",
        ret_autorizacao=f"{base}/nferetautorizacao4.asmx?wsdl",
        recepcao_evento=f"{base}/nferecepcaoevento4.asmx?wsdl",
    )


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
    def _transport(self):
        history = HistoryPlugin()
        session = requests.Session()
        session.timeout = self.timeout
        cert_files = None
        if self.pfx_bytes:
            cert_files = _pfx_to_temp_pem(self.pfx_bytes, self.pfx_password)
            session.cert = cert_files
        transport = Transport(session=session)
        try:
            yield history, transport
        finally:
            if cert_files:
                _cleanup_cert_files(cert_files)

    def _call(self, wsdl: str, operation: str, payload: dict[str, Any]) -> SefazSoapResponse:
        with self._transport() as (history, transport):
            client = Client(
                wsdl=wsdl,
                settings=Settings(strict=False, xml_huge_tree=True),
                transport=transport,
                plugins=[history],
            )
            try:
                service_method = getattr(client.service, operation)
                response = service_method(**payload)
                request_xml = _history_xml(history.last_sent)
                response_xml = _history_xml(history.last_received)
                return SefazSoapResponse(True, response, request_xml, response_xml)
            except Fault as exc:
                request_xml = _history_xml(history.last_sent)
                response_xml = _history_xml(history.last_received)
                return SefazSoapResponse(False, None, request_xml, response_xml, error_message=str(exc))
            except Exception as exc:  # noqa: BLE001
                request_xml = _history_xml(history.last_sent)
                response_xml = _history_xml(history.last_received)
                return SefazSoapResponse(False, None, request_xml, response_xml, error_message=str(exc))

    def autorizacao(self, xml_assinado: str) -> SefazSoapResponse:
        return self._call(
            self.wsdl_config.autorizacao,
            "nfeAutorizacaoLote",
            {"nfeDadosMsg": xml_assinado},
        )

    def ret_autorizacao(self, recibo: str) -> SefazSoapResponse:
        return self._call(
            self.wsdl_config.ret_autorizacao,
            "nfeRetAutorizacaoLote",
            {"nfeDadosMsg": recibo},
        )

    def evento_cancelamento(self, chave: str, xml_evento_assinado: str) -> SefazSoapResponse:
        return self._call(
            self.wsdl_config.recepcao_evento,
            "nfeRecepcaoEvento",
            {"nfeDadosMsg": xml_evento_assinado, "chNFe": chave},
        )

    def test_connection(self) -> SefazSoapResponse:
        """Carrega o WSDL para validar conectividade no ambiente configurado."""
        try:
            Client(wsdl=self.wsdl_config.autorizacao)
            return SefazSoapResponse(True, None, None, None)
        except Exception as exc:  # noqa: BLE001
            return SefazSoapResponse(False, None, None, None, error_message=str(exc))


def _history_xml(history_item) -> str | None:
    if not history_item:
        return None
    try:
        return history_item.envelope.decode("utf-8")
    except Exception:  # noqa: BLE001
        try:
            return history_item.envelope
        except Exception:  # noqa: BLE001
            return None


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
