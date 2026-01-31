"""Cliente SOAP Betha NFS-e usando Zeep."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
import tempfile
from typing import Any, Optional

from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, pkcs12
from zeep import Client, Settings
from zeep.exceptions import Fault
from zeep.plugins import HistoryPlugin
from zeep.transports import Transport
import requests


@dataclass
class BethaSoapResponse:
    success: bool
    response: Any | None
    request_xml: str | None
    response_xml: str | None
    error_message: str | None = None


@dataclass
class BethaWsdlConfig:
    recepcionar_lote_rps: str
    consultar_situacao_lote_rps: str
    consultar_nfse_por_rps: str
    cancelar_nfse: str


class BethaNfseClient:
    def __init__(
        self,
        wsdl_config: BethaWsdlConfig,
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

    def _call(self, wsdl: str, operation: str, payload: dict[str, Any]) -> BethaSoapResponse:
        with self._transport() as (history, transport):
            client = Client(wsdl=wsdl, settings=Settings(strict=False, xml_huge_tree=True), transport=transport, plugins=[history])
            try:
                service_method = getattr(client.service, operation)
                response = service_method(**payload)
                request_xml = _history_xml(history.last_sent)
                response_xml = _history_xml(history.last_received)
                return BethaSoapResponse(True, response, request_xml, response_xml)
            except Fault as exc:
                request_xml = _history_xml(history.last_sent)
                response_xml = _history_xml(history.last_received)
                return BethaSoapResponse(False, None, request_xml, response_xml, error_message=str(exc))
            except Exception as exc:  # noqa: BLE001
                request_xml = _history_xml(history.last_sent)
                response_xml = _history_xml(history.last_received)
                return BethaSoapResponse(False, None, request_xml, response_xml, error_message=str(exc))

    def recepcionar_lote_rps(self, payload: dict[str, Any]) -> BethaSoapResponse:
        return self._call(self.wsdl_config.recepcionar_lote_rps, "RecepcionarLoteRps", payload)

    def consultar_situacao_lote_rps(self, payload: dict[str, Any]) -> BethaSoapResponse:
        return self._call(self.wsdl_config.consultar_situacao_lote_rps, "ConsultarSituacaoLoteRps", payload)

    def consultar_nfse_por_rps(self, payload: dict[str, Any]) -> BethaSoapResponse:
        return self._call(self.wsdl_config.consultar_nfse_por_rps, "ConsultarNfsePorRps", payload)

    def cancelar_nfse(self, payload: dict[str, Any]) -> BethaSoapResponse:
        return self._call(self.wsdl_config.cancelar_nfse, "CancelarNfse", payload)

    def test_connection(self, payload: dict[str, Any]) -> BethaSoapResponse:
        """Executa uma chamada simples para validar conectividade com o WS."""
        return self.consultar_situacao_lote_rps(payload)


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
