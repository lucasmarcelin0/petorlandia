"""NFS-e service interface and municipal adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from typing import Any, Dict, Optional, Protocol
from xml.etree import ElementTree as ET

from flask import current_app, has_app_context
from cryptography.fernet import InvalidToken

from extensions import db
from models import Clinica, NfseIssue, NfseXml
from security.crypto import MissingMasterKeyError, decrypt_text
from time_utils import utcnow


@dataclass
class NfseCredentials:
    cert_path: Optional[str] = None
    cert_password: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    issuer_cnpj: Optional[str] = None
    issuer_inscricao_municipal: Optional[str] = None


@dataclass
class NfseOperationResult:
    success: bool
    status: str
    xml_request: Optional[str] = None
    xml_response: Optional[str] = None
    protocolo: Optional[str] = None
    numero_nfse: Optional[str] = None
    rps: Optional[str] = None
    serie: Optional[str] = None
    mensagem: Optional[str] = None
    erro_codigo: Optional[str] = None
    erro_detalhes: Optional[str] = None
    cancelada_em: Optional[datetime] = None


class NfseAdapter(Protocol):
    municipio: str

    def emitir_nfse(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        credentials: NfseCredentials,
    ) -> NfseOperationResult:
        ...

    def consultar_nfse(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        credentials: NfseCredentials,
    ) -> NfseOperationResult:
        ...

    def cancelar_nfse(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        credentials: NfseCredentials,
    ) -> NfseOperationResult:
        ...

    def consultar_lote(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        credentials: NfseCredentials,
    ) -> NfseOperationResult:
        ...


class NfseCredentialProvider:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = config or {}

    def get_credentials(self, clinica: Clinica, municipio: str) -> NfseCredentials:
        def _decrypt_if_needed(value: Optional[str]) -> Optional[str]:
            if not value:
                return None
            try:
                return decrypt_text(value)
            except InvalidToken:
                return value
            except MissingMasterKeyError as exc:
                raise RuntimeError(
                    "FISCAL_MASTER_KEY ausente; não foi possível descriptografar credenciais NFS-e."
                ) from exc

        municipio_key = _normalize_municipio(municipio)
        per_municipio = self._config.get(municipio_key, {})
        clinica_key = str(clinica.id)
        payload = per_municipio.get(clinica_key) or per_municipio.get("default") or {}
        if payload:
            base_credentials = NfseCredentials(
                cert_path=payload.get("cert_path"),
                cert_password=payload.get("cert_password"),
                username=payload.get("username"),
                password=payload.get("password"),
                token=payload.get("token"),
                issuer_cnpj=payload.get("issuer_cnpj") or clinica.cnpj,
                issuer_inscricao_municipal=payload.get("issuer_inscricao_municipal"),
            )
        else:
            base_credentials = _credentials_from_env(clinica, municipio_key)

        return NfseCredentials(
            cert_path=_decrypt_if_needed(
                clinica.get_nfse_encrypted("nfse_cert_path") or base_credentials.cert_path
            ),
            cert_password=_decrypt_if_needed(
                clinica.get_nfse_encrypted("nfse_cert_password") or base_credentials.cert_password
            ),
            username=_decrypt_if_needed(
                clinica.get_nfse_encrypted("nfse_username") or base_credentials.username
            ),
            password=_decrypt_if_needed(
                clinica.get_nfse_encrypted("nfse_password") or base_credentials.password
            ),
            token=_decrypt_if_needed(
                clinica.get_nfse_encrypted("nfse_token") or base_credentials.token
            ),
            issuer_cnpj=base_credentials.issuer_cnpj or clinica.cnpj,
            issuer_inscricao_municipal=(
                clinica.inscricao_municipal or base_credentials.issuer_inscricao_municipal
            ),
        )


class NfseService:
    def __init__(
        self,
        adapters: Optional[Dict[str, NfseAdapter]] = None,
        credential_provider: Optional[NfseCredentialProvider] = None,
    ) -> None:
        self.adapters = adapters or {
            "belo_horizonte": BeloHorizonteAdapter(),
            "orlandia": OrlandiaAdapter(),
        }
        config = None
        if has_app_context():
            config = current_app.config.get("NFSE_CREDENTIALS")
        self.credential_provider = credential_provider or NfseCredentialProvider(config)

    def emitir_nfse(self, issue: NfseIssue, payload: Dict[str, Any], municipio: str) -> NfseOperationResult:
        adapter = self._resolve_adapter(municipio)
        credentials = self.credential_provider.get_credentials(issue.clinica, municipio)
        result = adapter.emitir_nfse(issue, payload, credentials)
        self._apply_result(issue, result, operation="emitir_nfse")
        return result

    def consultar_nfse(self, issue: NfseIssue, payload: Dict[str, Any], municipio: str) -> NfseOperationResult:
        adapter = self._resolve_adapter(municipio)
        credentials = self.credential_provider.get_credentials(issue.clinica, municipio)
        result = adapter.consultar_nfse(issue, payload, credentials)
        self._apply_result(issue, result, operation="consultar_nfse")
        return result

    def cancelar_nfse(self, issue: NfseIssue, payload: Dict[str, Any], municipio: str) -> NfseOperationResult:
        adapter = self._resolve_adapter(municipio)
        credentials = self.credential_provider.get_credentials(issue.clinica, municipio)
        result = adapter.cancelar_nfse(issue, payload, credentials)
        self._apply_result(issue, result, operation="cancelar_nfse")
        return result

    def consultar_lote(self, issue: NfseIssue, payload: Dict[str, Any], municipio: str) -> NfseOperationResult:
        adapter = self._resolve_adapter(municipio)
        credentials = self.credential_provider.get_credentials(issue.clinica, municipio)
        result = adapter.consultar_lote(issue, payload, credentials)
        self._apply_result(issue, result, operation="consultar_lote")
        return result

    def _resolve_adapter(self, municipio: str) -> NfseAdapter:
        municipio_key = _normalize_municipio(municipio)
        try:
            return self.adapters[municipio_key]
        except KeyError as exc:
            raise ValueError(f"Municipio '{municipio}' não suportado") from exc

    def _apply_result(
        self,
        issue: NfseIssue,
        result: NfseOperationResult,
        operation: str,
    ) -> None:
        _enrich_nfse_error(result)
        issue.status = result.status
        if result.protocolo:
            issue.protocolo = result.protocolo
        if result.numero_nfse:
            issue.numero_nfse = result.numero_nfse
        if result.rps:
            issue.rps = result.rps
        if result.serie:
            issue.serie = result.serie
        if result.xml_request:
            issue.xml_envio = result.xml_request
        if result.xml_response:
            issue.xml_retorno = result.xml_response
        if result.cancelada_em:
            issue.cancelada_em = result.cancelada_em
        if not result.success:
            issue.erro_codigo = result.erro_codigo
            issue.erro_mensagem = result.mensagem
            issue.erro_detalhes = result.erro_detalhes
            issue.erro_em = utcnow()
        _record_xml(issue, result, operation)
        db.session.add(issue)
        db.session.commit()


class NfseAdapterBase:
    municipio: str = ""

    def _build_envelope(self, action: str, payload: Dict[str, Any]) -> str:
        raw_xml = payload.get("xml")
        if raw_xml:
            return raw_xml
        return (
            f"<soap:Envelope xmlns:soap=\"http://schemas.xmlsoap.org/soap/envelope/\">"
            f"<soap:Body><{action}>{payload}</{action}></soap:Body></soap:Envelope>"
        )

    def _response_stub(self, action: str, status: str, message: str) -> str:
        return (
            f"<Resposta{action}><Status>{status}</Status><Mensagem>{message}</Mensagem>"
            f"</Resposta{action}>"
        )


class BeloHorizonteAdapter(NfseAdapterBase):
    municipio = "belo_horizonte"

    def emitir_nfse(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        credentials: NfseCredentials,
    ) -> NfseOperationResult:
        request_xml = self._build_envelope("EnviarLoteRps", payload)
        response_xml = self._response_stub("EnviarLoteRps", "PROCESSANDO", "Lote enviado para BH")
        protocolo = payload.get("protocolo") or f"BH-{issue.id}-{utcnow().strftime('%Y%m%d%H%M%S')}"
        return NfseOperationResult(
            success=True,
            status="processando",
            xml_request=request_xml,
            xml_response=response_xml,
            protocolo=protocolo,
            rps=payload.get("rps") or issue.rps,
            serie=payload.get("serie") or issue.serie,
            mensagem="Envio registrado localmente; aguarde consulta de lote.",
        )

    def consultar_nfse(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        credentials: NfseCredentials,
    ) -> NfseOperationResult:
        request_xml = self._build_envelope("ConsultarNfse", payload)
        response_xml = self._response_stub("ConsultarNfse", "PENDENTE", "Consulta registrada")
        return NfseOperationResult(
            success=True,
            status="pendente",
            xml_request=request_xml,
            xml_response=response_xml,
            protocolo=payload.get("protocolo") or issue.protocolo,
            numero_nfse=payload.get("numero_nfse") or issue.numero_nfse,
            mensagem="Consulta registrada para BH.",
        )

    def cancelar_nfse(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        credentials: NfseCredentials,
    ) -> NfseOperationResult:
        request_xml = self._build_envelope("CancelarNfse", payload)
        response_xml = self._response_stub("CancelarNfse", "PROCESSANDO", "Cancelamento solicitado")
        return NfseOperationResult(
            success=True,
            status="cancelamento_solicitado",
            xml_request=request_xml,
            xml_response=response_xml,
            protocolo=payload.get("protocolo") or issue.protocolo,
            numero_nfse=payload.get("numero_nfse") or issue.numero_nfse,
            cancelada_em=None,
            mensagem="Cancelamento solicitado para BH.",
        )

    def consultar_lote(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        credentials: NfseCredentials,
    ) -> NfseOperationResult:
        request_xml = self._build_envelope("ConsultarLoteRps", payload)
        response_xml = self._response_stub("ConsultarLoteRps", "PENDENTE", "Lote em processamento")
        return NfseOperationResult(
            success=True,
            status="processando",
            xml_request=request_xml,
            xml_response=response_xml,
            protocolo=payload.get("protocolo") or issue.protocolo,
            mensagem="Lote ainda em processamento em BH.",
        )


class OrlandiaAdapter(NfseAdapterBase):
    municipio = "orlandia"

    def emitir_nfse(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        credentials: NfseCredentials,
    ) -> NfseOperationResult:
        request_xml = self._build_envelope("GerarNfse", payload)
        response_xml = self._response_stub("GerarNfse", "PROCESSANDO", "Envio registrado")
        protocolo = payload.get("protocolo") or f"ORL-{issue.id}-{utcnow().strftime('%Y%m%d%H%M%S')}"
        return NfseOperationResult(
            success=True,
            status="processando",
            xml_request=request_xml,
            xml_response=response_xml,
            protocolo=protocolo,
            rps=payload.get("rps") or issue.rps,
            serie=payload.get("serie") or issue.serie,
            mensagem="Envio registrado localmente; aguarde consulta.",
        )

    def consultar_nfse(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        credentials: NfseCredentials,
    ) -> NfseOperationResult:
        request_xml = self._build_envelope("ConsultarNfse", payload)
        response_xml = self._response_stub("ConsultarNfse", "PENDENTE", "Consulta registrada")
        return NfseOperationResult(
            success=True,
            status="pendente",
            xml_request=request_xml,
            xml_response=response_xml,
            protocolo=payload.get("protocolo") or issue.protocolo,
            numero_nfse=payload.get("numero_nfse") or issue.numero_nfse,
            mensagem="Consulta registrada para Orlândia.",
        )

    def cancelar_nfse(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        credentials: NfseCredentials,
    ) -> NfseOperationResult:
        request_xml = self._build_envelope("CancelarNfse", payload)
        response_xml = self._response_stub("CancelarNfse", "PROCESSANDO", "Cancelamento solicitado")
        return NfseOperationResult(
            success=True,
            status="cancelamento_solicitado",
            xml_request=request_xml,
            xml_response=response_xml,
            protocolo=payload.get("protocolo") or issue.protocolo,
            numero_nfse=payload.get("numero_nfse") or issue.numero_nfse,
            cancelada_em=None,
            mensagem="Cancelamento solicitado para Orlândia.",
        )

    def consultar_lote(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        credentials: NfseCredentials,
    ) -> NfseOperationResult:
        request_xml = self._build_envelope("ConsultarLoteRps", payload)
        response_xml = self._response_stub("ConsultarLoteRps", "PENDENTE", "Lote em processamento")
        return NfseOperationResult(
            success=True,
            status="processando",
            xml_request=request_xml,
            xml_response=response_xml,
            protocolo=payload.get("protocolo") or issue.protocolo,
            mensagem="Lote ainda em processamento em Orlândia.",
        )


def _normalize_municipio(municipio: str) -> str:
    normalized = municipio.strip().lower().replace("-", " ")
    normalized = normalized.replace("á", "a").replace("â", "a").replace("ã", "a")
    normalized = normalized.replace("é", "e").replace("ê", "e")
    normalized = normalized.replace("í", "i")
    normalized = normalized.replace("ó", "o").replace("ô", "o")
    normalized = normalized.replace("ú", "u")
    normalized = " ".join(normalized.split())
    if normalized in {"bh", "belo horizonte", "belo horizonte mg", "belo horizonte/mg"}:
        return "belo_horizonte"
    if normalized in {"orlandia", "orlandia sp", "orlandia/sp"}:
        return "orlandia"
    return normalized.replace(" ", "_")


def _enrich_nfse_error(result: NfseOperationResult) -> None:
    if result.success:
        return
    message = (result.mensagem or "").strip() or None
    code = (result.erro_codigo or "").strip() or None
    details = (result.erro_detalhes or "").strip() or None
    parsed_code, parsed_message, parsed_details = _parse_nfse_error_xml(result.xml_response or "")
    message = message or parsed_message
    code = code or parsed_code
    details = details or parsed_details
    if not message and result.xml_response:
        message = "Não foi possível processar a resposta da NFS-e."
        details = details or _compact_xml(result.xml_response)
    result.mensagem = message
    result.erro_codigo = code
    result.erro_detalhes = details


def _parse_nfse_error_xml(xml_text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if not xml_text:
        return None, None, None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None, None, None

    def _local(tag: str) -> str:
        return tag.split("}", 1)[-1].lower()

    def _text(elem) -> Optional[str]:
        text = "".join(elem.itertext()).strip()
        return text or None

    fault_string = None
    fault_code = None
    detail_text = None
    message = None
    code = None
    details = None

    for elem in root.iter():
        tag = _local(elem.tag)
        if tag == "faultstring" and not fault_string:
            fault_string = _text(elem)
        if tag == "faultcode" and not fault_code:
            fault_code = _text(elem)
        if tag in {"detail", "details", "detalhe", "detalhes"} and not detail_text:
            detail_text = _text(elem)
        if tag in {"mensagemerro", "mensagem", "descricao", "erro", "error"} and not message:
            message = _text(elem)
        if tag in {"codigo", "codigoerro", "code"} and not code:
            code = _text(elem)

    return (
        code or fault_code,
        message or fault_string,
        detail_text,
    )


def _compact_xml(xml_text: str, max_length: int = 500) -> str:
    compact = " ".join(xml_text.split())
    if len(compact) <= max_length:
        return compact
    return f"{compact[:max_length].rstrip()}..."


def _credentials_from_env(clinica: Clinica, municipio_key: str) -> NfseCredentials:
    upper = municipio_key.upper()
    clinica_suffix = f"_CLINICA_{clinica.id}"
    def _env(name: str) -> Optional[str]:
        return os.environ.get(f"NFSE_{upper}_{name}{clinica_suffix}") or os.environ.get(
            f"NFSE_{upper}_{name}"
        )

    return NfseCredentials(
        cert_path=_env("CERT_PATH"),
        cert_password=_env("CERT_PASSWORD"),
        username=_env("USERNAME"),
        password=_env("PASSWORD"),
        token=_env("TOKEN"),
        issuer_cnpj=_env("ISSUER_CNPJ") or clinica.cnpj,
        issuer_inscricao_municipal=_env("ISSUER_IM"),
    )


def _record_xml(issue: NfseIssue, result: NfseOperationResult, operation: str) -> None:
    if result.xml_request:
        db.session.add(
            NfseXml(
                clinica_id=issue.clinica_id,
                nfse_issue_id=issue.id,
                rps=result.rps or issue.rps,
                numero_nfse=result.numero_nfse or issue.numero_nfse,
                serie=result.serie or issue.serie,
                protocolo=result.protocolo or issue.protocolo,
                tipo=f"{operation}_envio",
                xml=result.xml_request,
            )
        )
    if result.xml_response:
        db.session.add(
            NfseXml(
                clinica_id=issue.clinica_id,
                nfse_issue_id=issue.id,
                rps=result.rps or issue.rps,
                numero_nfse=result.numero_nfse or issue.numero_nfse,
                serie=result.serie or issue.serie,
                protocolo=result.protocolo or issue.protocolo,
                tipo=f"{operation}_retorno",
                xml=result.xml_response,
            )
        )
