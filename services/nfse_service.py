"""NFS-e service interface and municipal adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
import os
import re
from typing import Any, Dict, Optional, Protocol
# Parsing de XML externo (resposta de prefeitura): usamos defusedxml.ElementTree
# como drop-in do stdlib para blindar XXE, billion-laughs, SSRF via DTD.
# Veja security/xml_safe.py para a justificativa detalhada.
from xml.etree import ElementTree as _ET_NATIVE  # só para os tipos de exceção
from security.xml_safe import SafeET as ET

import logging

from flask import current_app, has_app_context
from cryptography.fernet import InvalidToken

from extensions import db
from models import (
    Clinica,
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalDocumentType,
    FiscalEmitter,
    NfseIssue,
    NfseXml,
)
from security.crypto import MissingMasterKeyError, decrypt_text, encrypt_text_for_clinic
from services.fiscal.nfse_service import (
    cancel_nfse_document,
    emit_nfse_sync,
    poll_nfse,
)
from services.fiscal.numbering import reserve_next_number
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

    def _run_fiscal_document_operation(
        self,
        issue: NfseIssue,
        payload: Dict[str, Any],
        operation: str,
    ) -> NfseOperationResult:
        document = _ensure_fiscal_document_for_issue(issue, payload, self.municipio)
        if operation == "emitir":
            document = emit_nfse_sync(document.id, clinic_id=issue.clinica_id)
        elif operation in {"consultar_nfse", "consultar_lote"}:
            document = poll_nfse(document.id, clinic_id=issue.clinica_id)
        elif operation == "cancelar":
            document = cancel_nfse_document(document.id, payload.get("reason"), clinic_id=issue.clinica_id)
        else:  # pragma: no cover
            raise ValueError(f"Operacao NFS-e invalida: {operation}")
        _sync_issue_from_fiscal_document(issue, document)
        return _result_from_fiscal_document(document, operation)


class BeloHorizonteAdapter(NfseAdapterBase):
    municipio = "belo_horizonte"

    def emitir_nfse(self, issue: NfseIssue, payload: Dict[str, Any], credentials: NfseCredentials) -> NfseOperationResult:
        return self._run_fiscal_document_operation(issue, payload, "emitir")

    def consultar_nfse(self, issue: NfseIssue, payload: Dict[str, Any], credentials: NfseCredentials) -> NfseOperationResult:
        return self._run_fiscal_document_operation(issue, payload, "consultar_nfse")

    def cancelar_nfse(self, issue: NfseIssue, payload: Dict[str, Any], credentials: NfseCredentials) -> NfseOperationResult:
        return self._run_fiscal_document_operation(issue, payload, "cancelar")

    def consultar_lote(self, issue: NfseIssue, payload: Dict[str, Any], credentials: NfseCredentials) -> NfseOperationResult:
        return self._run_fiscal_document_operation(issue, payload, "consultar_lote")


class OrlandiaAdapter(NfseAdapterBase):
    municipio = "orlandia"

    def emitir_nfse(self, issue: NfseIssue, payload: Dict[str, Any], credentials: NfseCredentials) -> NfseOperationResult:
        return self._run_fiscal_document_operation(issue, payload, "emitir")

    def consultar_nfse(self, issue: NfseIssue, payload: Dict[str, Any], credentials: NfseCredentials) -> NfseOperationResult:
        return self._run_fiscal_document_operation(issue, payload, "consultar_nfse")

    def cancelar_nfse(self, issue: NfseIssue, payload: Dict[str, Any], credentials: NfseCredentials) -> NfseOperationResult:
        return self._run_fiscal_document_operation(issue, payload, "cancelar")

    def consultar_lote(self, issue: NfseIssue, payload: Dict[str, Any], credentials: NfseCredentials) -> NfseOperationResult:
        return self._run_fiscal_document_operation(issue, payload, "consultar_lote")


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


def _load_json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _payload_from_issue(issue: NfseIssue, payload: Dict[str, Any]) -> dict[str, Any]:
    merged = dict(payload or {})
    tomador = merged.get("tomador") or _load_json_payload(issue.tomador)
    prestador = merged.get("prestador") or _load_json_payload(issue.prestador)
    valor_total = merged.get("valor_total")
    if valor_total is None:
        valor_total = issue.valor_total or Decimal("0.00")
    servico = merged.get("servico") or {
        "descricao": merged.get("descricao") or "Atendimento veterinario",
        "valor": valor_total,
        "item_lista": merged.get("codigo_servico") or "0000",
    }
    rps_payload = dict(merged.get("rps") or {})
    rps_payload.setdefault("serie", issue.serie or merged.get("serie") or "1")
    if issue.data_emissao:
        rps_payload.setdefault("data_emissao", issue.data_emissao.isoformat())
    merged.update(
        {
            "prestador": {
                "cnpj": prestador.get("cnpj") or prestador.get("cpf_cnpj"),
                "im": prestador.get("im") or prestador.get("inscricao_municipal"),
                **prestador,
            },
            "tomador": {
                "nome": tomador.get("nome") or tomador.get("tomador_nome") or tomador.get("tutor_nome"),
                "cpf_cnpj": tomador.get("cpf_cnpj") or tomador.get("tutor_documento"),
                **tomador,
            },
            "servico": servico,
            "valor_total": valor_total,
            "rps": rps_payload,
        }
    )
    return _json_ready(merged)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _ensure_fiscal_document_for_issue(
    issue: NfseIssue,
    payload: Dict[str, Any],
    municipio: str,
) -> FiscalDocument:
    emitter = FiscalEmitter.query.filter_by(clinic_id=issue.clinica_id).first()
    if not emitter:
        raise ValueError("Emissor fiscal nao configurado para a clinica.")
    document = (
        FiscalDocument.query.filter_by(
            clinic_id=issue.clinica_id,
            doc_type=FiscalDocumentType.NFSE,
            source_type="NFSE_ISSUE",
            source_id=issue.id,
        )
        .order_by(FiscalDocument.created_at.desc())
        .first()
    )
    normalized_payload = _payload_from_issue(issue, payload)
    series = str(
        normalized_payload.get("serie")
        or (normalized_payload.get("rps") or {}).get("serie")
        or issue.serie
        or "1"
    )
    if document is None:
        number = reserve_next_number(emitter.id, FiscalDocumentType.NFSE, series)
        normalized_payload.setdefault("rps", {})
        normalized_payload["rps"]["numero"] = number
        normalized_payload["rps"]["serie"] = series
        document = FiscalDocument(
            emitter_id=emitter.id,
            clinic_id=issue.clinica_id,
            doc_type=FiscalDocumentType.NFSE,
            status=FiscalDocumentStatus.DRAFT,
            series=series,
            number=number,
            payload_json=normalized_payload,
            source_type="NFSE_ISSUE",
            source_id=issue.id,
            related_type="nfse_issue",
            related_id=issue.id,
            human_reference=issue.internal_identifier or f"NFS-e issue #{issue.id}",
            animal_name=issue.animal_display_name,
            tutor_name=issue.tutor_display_name,
        )
        db.session.add(document)
        db.session.flush()
    else:
        normalized_payload.setdefault("rps", {})
        normalized_payload["rps"].setdefault("numero", document.number)
        normalized_payload["rps"].setdefault("serie", document.series or series)
        document.payload_json = normalized_payload
        document.emitter_id = emitter.id
    issue.rps = str(document.number or issue.rps or "")
    issue.serie = document.series or issue.serie
    return document


def _legacy_status_from_document(status: FiscalDocumentStatus) -> str:
    return {
        FiscalDocumentStatus.DRAFT: "rascunho",
        FiscalDocumentStatus.QUEUED: "fila",
        FiscalDocumentStatus.SENDING: "processando",
        FiscalDocumentStatus.PROCESSING: "processando",
        FiscalDocumentStatus.AUTHORIZED: "emitida",
        FiscalDocumentStatus.REJECTED: "erro",
        FiscalDocumentStatus.FAILED: "erro",
        FiscalDocumentStatus.CANCELED: "cancelada",
    }.get(status, "erro")


def _last_document_event_xml(document: FiscalDocument) -> tuple[str | None, str | None]:
    event = (
        document.events[-1]
        if getattr(document, "events", None)
        else None
    )
    if event is None:
        return None, None
    return event.request_xml, event.response_xml


def _sync_issue_from_fiscal_document(issue: NfseIssue, document: FiscalDocument) -> None:
    issue.status = _legacy_status_from_document(document.status)
    issue.protocolo = document.protocol or issue.protocolo
    issue.numero_nfse = document.nfse_number or issue.numero_nfse
    issue.rps = str(document.number or issue.rps or "")
    issue.serie = document.series or issue.serie
    issue.erro_codigo = document.error_code or issue.erro_codigo
    issue.erro_mensagem = document.error_message or issue.erro_mensagem
    if document.authorized_at:
        issue.data_emissao = document.authorized_at
    if document.canceled_at:
        issue.cancelada_em = document.canceled_at
    issue.updated_at = utcnow()
    db.session.add(issue)


def _result_from_fiscal_document(document: FiscalDocument, operation: str) -> NfseOperationResult:
    request_xml, response_xml = _last_document_event_xml(document)
    status = _legacy_status_from_document(document.status)
    success = document.status in {
        FiscalDocumentStatus.PROCESSING,
        FiscalDocumentStatus.AUTHORIZED,
        FiscalDocumentStatus.CANCELED,
    }
    return NfseOperationResult(
        success=success,
        status=status,
        xml_request=request_xml,
        xml_response=response_xml,
        protocolo=document.protocol,
        numero_nfse=document.nfse_number,
        rps=str(document.number or ""),
        serie=document.series,
        mensagem=document.error_message or f"Operacao {operation} registrada no documento fiscal.",
        erro_codigo=document.error_code,
        erro_detalhes=document.error_message,
        cancelada_em=document.canceled_at,
    )


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
    except _ET_NATIVE.ParseError:
        # defusedxml re-levanta a ParseError nativa do stdlib; o except precisa
        # apontar para a classe real, não para o alias SafeET.
        return None, None, None
    except Exception:
        # defusedxml levanta EntitiesForbidden/DTDForbidden/ExternalReferenceForbidden
        # em caso de ataque — aqui tratamos como "XML inválido" do ponto de vista
        # da prefeitura, sem vazar o tipo exato pro chamador.
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
    compact = " ".join(_redact_sensitive_xml_text(xml_text).split())
    if len(compact) <= max_length:
        return compact
    return f"{compact[:max_length].rstrip()}..."


def _redact_sensitive_xml_text(xml_text: str) -> str:
    text = xml_text or ""
    for tag in ("Cpf", "Cnpj", "InscricaoMunicipal", "Senha", "Password", "Token"):
        text = re.sub(
            rf"(<(?:\w+:)?{tag}\b[^>]*>)(.*?)(</(?:\w+:)?{tag}>)",
            rf"\1***\3",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    text = re.sub(r"\b\d{11}\b", "***", text)
    text = re.sub(r"\b\d{14}\b", "***", text)
    return text


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
    logger = current_app.logger if has_app_context() else logging.getLogger(__name__)

    def _encrypt_payload(xml_text: str) -> str:
        try:
            return encrypt_text_for_clinic(issue.clinica_id, xml_text)
        except MissingMasterKeyError as exc:
            logger.error(
                "Falha ao criptografar XML da NFS-e para clinica %s (issue %s).",
                issue.clinica_id,
                issue.id,
            )
            raise RuntimeError(
                "FISCAL_MASTER_KEY ausente; não foi possível criptografar XML da NFS-e."
            ) from exc

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
                xml=_encrypt_payload(result.xml_request),
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
                xml=_encrypt_payload(result.xml_response),
            )
        )
