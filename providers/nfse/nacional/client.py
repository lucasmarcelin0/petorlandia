"""REST client for the Sistema Nacional NFS-e public issuer API."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import base64
import gzip
import json
import os
import tempfile
from typing import Any, Optional

from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, pkcs12
from lxml import etree
import requests

from security.xml_safe import safe_lxml_fromstring


DEFAULT_RESTRICTED_BASE_URL = "https://sefin.producaorestrita.nfse.gov.br/SefinNacional"
DEFAULT_PRODUCTION_BASE_URL = "https://sefin.nfse.gov.br/SefinNacional"


@dataclass
class NacionalNfseConfig:
    base_url: str = DEFAULT_RESTRICTED_BASE_URL
    environment: str = "producao_restrita"
    production_base_url: str = DEFAULT_PRODUCTION_BASE_URL
    timeout: int = 30
    nfse_path: str = "/nfse"
    dps_path: str = "/dps/{id}"
    eventos_path: str = "/nfse/{chave_acesso}/eventos"


@dataclass
class NacionalNfseResponse:
    success: bool
    status_code: int | None
    request_xml: str | None
    response_xml: str | None
    response_json: dict[str, Any] | list[Any] | None
    response_text: str | None
    error_message: str | None = None
    protocol: str | None = None
    nfse_number: str | None = None
    access_key: str | None = None
    verification_code: str | None = None


def encode_gzip_b64(xml: str) -> str:
    return base64.b64encode(gzip.compress(xml.encode("utf-8"))).decode("ascii")


def decode_gzip_b64(value: str | None) -> str | None:
    if not value:
        return None
    try:
        compressed = base64.b64decode(value)
        return gzip.decompress(compressed).decode("utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _extract_key(payload: Any, names: set[str]) -> Any | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in names:
                return value
            found = _extract_key(value, names)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_key(item, names)
            if found is not None:
                return found
    return None


def _format_error(payload: Any, fallback: str | None = None) -> str | None:
    errors = _extract_key(payload, {"erros", "Erros", "mensagens", "Mensagens"})
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            code = first.get("Codigo") or first.get("codigo") or first.get("code")
            desc = first.get("Descricao") or first.get("descricao") or first.get("message")
            return f"{code}: {desc}" if code and desc else (desc or code or fallback)
        return str(first)
    message = _extract_key(payload, {"mensagem", "message", "Message", "detail", "title"})
    return str(message) if message else fallback


def _local_name(tag: Any) -> str:
    return str(tag).split("}", 1)[-1]


def _extract_xml_field(xml: str | None, local_names: set[str]) -> str | None:
    if not xml:
        return None
    try:
        root = safe_lxml_fromstring(xml)
    except Exception:
        return None
    for node in root.iter():
        local = _local_name(node.tag)
        if local in local_names and node.text:
            return node.text.strip()
        if local in {"infNFSe", "infDFe"}:
            node_id = node.get("Id")
            if node_id and node_id.startswith("NFS") and "chNFSe" in local_names:
                return node_id[3:]
    return None


def _extract_response_xml(payload: Any) -> str | None:
    xml_text = _extract_key(payload, {"nfseXml", "xml", "Xml", "NFSeXml", "dpsXml"})
    if isinstance(xml_text, str) and xml_text.lstrip().startswith("<"):
        return xml_text
    b64_text = _extract_key(
        payload,
        {
            "nfseXmlGZipB64",
            "nfseXmlGzipB64",
            "xmlGZipB64",
            "xmlGzipB64",
            "DPSXmlGZipB64",
            "dpsXmlGZipB64",
        },
    )
    if isinstance(b64_text, str):
        return decode_gzip_b64(b64_text)
    return None


class NacionalNfseClient:
    def __init__(
        self,
        config: NacionalNfseConfig,
        *,
        pfx_bytes: Optional[bytes] = None,
        pfx_password: Optional[str] = None,
    ) -> None:
        self.config = config
        self.pfx_bytes = pfx_bytes
        self.pfx_password = pfx_password

    @property
    def base_url(self) -> str:
        base = self.config.base_url
        if self.config.environment == "producao" and base == DEFAULT_RESTRICTED_BASE_URL:
            base = self.config.production_base_url
        return base.rstrip("/")

    @contextmanager
    def _session(self):
        session = requests.Session()
        cert_files = None
        if self.pfx_bytes:
            cert_files = _pfx_to_temp_pem(self.pfx_bytes, self.pfx_password)
            session.cert = cert_files
        try:
            yield session
        finally:
            session.close()
            if cert_files:
                _cleanup_cert_files(cert_files)

    def emitir_dps(self, signed_xml: str) -> NacionalNfseResponse:
        body = {"dpsXmlGZipB64": encode_gzip_b64(signed_xml)}
        return self._request("POST", self.config.nfse_path, json_body=body, request_xml=signed_xml)

    def consultar_nfse(self, chave_acesso: str) -> NacionalNfseResponse:
        path = f"{self.config.nfse_path.rstrip('/')}/{chave_acesso}"
        return self._request("GET", path)

    def consultar_dps(self, dps_id: str) -> NacionalNfseResponse:
        return self._request("GET", self.config.dps_path.format(id=dps_id))

    def registrar_evento(self, chave_acesso: str, signed_event_xml: str) -> NacionalNfseResponse:
        body = {"pedidoRegistroEventoXmlGZipB64": encode_gzip_b64(signed_event_xml)}
        path = self.config.eventos_path.format(chave_acesso=chave_acesso)
        return self._request("POST", path, json_body=body, request_xml=signed_event_xml)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        request_xml: str | None = None,
    ) -> NacionalNfseResponse:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            with self._session() as session:
                response = session.request(
                    method,
                    url,
                    json=json_body,
                    timeout=self.config.timeout,
                    headers={"Accept": "application/json"},
                )
        except requests.RequestException as exc:
            return NacionalNfseResponse(
                success=False,
                status_code=None,
                request_xml=request_xml,
                response_xml=None,
                response_json=None,
                response_text=None,
                error_message=str(exc),
            )
        return self._parse_response(response, request_xml=request_xml)

    def _parse_response(self, response: requests.Response, *, request_xml: str | None = None) -> NacionalNfseResponse:
        response_text = response.text
        response_json: dict[str, Any] | list[Any] | None = None
        try:
            response_json = response.json()
        except ValueError:
            response_json = None

        response_xml = None
        if response_json is not None:
            response_xml = _extract_response_xml(response_json)
        elif response_text.lstrip().startswith("<"):
            response_xml = response_text

        access_key = None
        nfse_number = None
        verification_code = None
        protocol = None
        if response_json is not None:
            key_value = _extract_key(response_json, {"chaveAcesso", "chave_acesso", "chNFSe", "ChaveAcesso"})
            access_key = str(key_value) if key_value else None
            protocol_value = _extract_key(response_json, {"protocolo", "Protocolo", "idDPS"})
            protocol = str(protocol_value) if protocol_value else None
        if response_xml:
            access_key = access_key or _extract_xml_field(response_xml, {"chNFSe"})
            nfse_number = _extract_xml_field(response_xml, {"nNFSe", "Numero", "numero"})
            verification_code = _extract_xml_field(response_xml, {"cVerif", "CodigoVerificacao"})
        if access_key:
            access_key = re_digits(access_key)

        error_message = None
        if response_json is not None:
            error_message = _format_error(response_json)
        if not error_message and not response.ok:
            error_message = response_text[:500] if response_text else f"HTTP {response.status_code}"

        return NacionalNfseResponse(
            success=response.ok and not error_message,
            status_code=response.status_code,
            request_xml=request_xml,
            response_xml=response_xml,
            response_json=response_json,
            response_text=response_text,
            error_message=error_message,
            protocol=protocol,
            nfse_number=nfse_number,
            access_key=access_key,
            verification_code=verification_code,
        )


def re_digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _pfx_to_temp_pem(pfx_bytes: bytes, password: str | None) -> tuple[str, str]:
    password_bytes = password.encode("utf-8") if password else None
    private_key, certificate, additional = pkcs12.load_key_and_certificates(
        pfx_bytes,
        password_bytes,
    )
    if private_key is None or certificate is None:
        raise ValueError("Certificado A1 invalido para conexao TLS.")

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
