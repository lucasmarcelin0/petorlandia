"""Cliente SOAP NF-e SEFAZ SP usando Zeep."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import logging
import os
import tempfile
from typing import Any, Optional

from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, pkcs12
from zeep import Client, Settings
from zeep.exceptions import Fault, TransportError, XMLSyntaxError as ZeepXMLSyntaxError
from zeep.plugins import HistoryPlugin
from zeep.transports import Transport
import requests


logger = logging.getLogger(__name__)


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
                # Fault = erro de negócio do SEFAZ (rejeição normativa).
                # Não é bug: log em WARNING para ficar visível sem ruído.
                request_xml = _history_xml(history.last_sent)
                response_xml = _history_xml(history.last_received)
                logger.warning(
                    "SEFAZ SP retornou Fault em %s: %s", operation, exc,
                )
                return SefazSoapResponse(False, None, request_xml, response_xml, error_message=str(exc))
            except (requests.RequestException, TransportError, ZeepXMLSyntaxError, OSError) as exc:
                # Falhas de rede/TLS/parsing da resposta. NÃO são bug nosso,
                # mas precisam de traceback: sem log, a operação "some" da
                # cadeia de erros — o chamador só vê a string opaca.
                request_xml = _history_xml(history.last_sent)
                response_xml = _history_xml(history.last_received)
                logger.exception(
                    "Erro de transporte/parsing em %s contra SEFAZ SP.",
                    operation,
                )
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
        # test_connection é o ponto onde o usuário clica "testar certificado"
        # no onboarding. Se algo estourar aqui e não logarmos, a UI mostra
        # só "Erro inesperado" e o suporte fica cego.
        try:
            Client(wsdl=self.wsdl_config.autorizacao)
            return SefazSoapResponse(True, None, None, None)
        except (requests.RequestException, TransportError, ZeepXMLSyntaxError, OSError) as exc:
            logger.exception("Falha ao carregar WSDL SEFAZ SP em test_connection.")
            return SefazSoapResponse(False, None, None, None, error_message=str(exc))


def _history_xml(history_item) -> str | None:
    # Zeep's HistoryPlugin.last_sent/last_received retorna dict com
    # .envelope em bytes (sucesso) ou lxml._Element (erro). Tratamos ambos.
    # Qualquer acesso que não seja AttributeError/UnicodeDecodeError seria
    # bug de zeep — deixamos estourar.
    if not history_item:
        return None
    envelope = getattr(history_item, "envelope", None)
    if envelope is None:
        return None
    if isinstance(envelope, bytes):
        try:
            return envelope.decode("utf-8")
        except UnicodeDecodeError:
            return envelope.decode("utf-8", errors="replace")
    # lxml _Element ou string: devolve como está.
    return str(envelope) if not isinstance(envelope, str) else envelope


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
