"""Helpers for handling fiscal certificates."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from cryptography import x509
from cryptography.x509.oid import ObjectIdentifier, NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs12


_CNPJ_PATTERN = re.compile(
    r"(?:CNPJ|Cadastro\s+Nacional\s+de\s+Pessoa\s+Jur[ií]dica|Pessoa\s+Jur[ií]dica)\D{0,20}(\d{14})",
    re.IGNORECASE,
)
_ICP_BRASIL_CNPJ_OID = ObjectIdentifier("2.16.76.1.3.3")


def _normalize_cnpj(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _ensure_timezone(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _extract_subject_cnpj(certificate: x509.Certificate) -> str | None:
    for attribute in certificate.subject:
        raw_value = attribute.value
        if not isinstance(raw_value, str):
            continue
        if attribute.oid == _ICP_BRASIL_CNPJ_OID:
            digits = _normalize_cnpj(raw_value)
            if len(digits) == 14:
                return digits
        if attribute.oid in {NameOID.SERIAL_NUMBER, NameOID.ORGANIZATION_NAME, NameOID.COMMON_NAME}:
            match = _CNPJ_PATTERN.search(raw_value)
            if match:
                return match.group(1)
    subject_text = certificate.subject.rfc4514_string()
    match = _CNPJ_PATTERN.search(subject_text)
    if match:
        return match.group(1)
    return None


def parse_pfx(pfx_bytes: bytes, password: str | None) -> dict:
    password_bytes = None
    if password is not None:
        password_bytes = password.encode("utf-8")
    private_key, certificate, _additional = pkcs12.load_key_and_certificates(
        pfx_bytes,
        password_bytes,
    )
    if certificate is None:
        raise ValueError("Nenhum certificado encontrado no arquivo PFX.")

    fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
    subject_cnpj = _extract_subject_cnpj(certificate)

    return {
        "certificate": certificate,
        "private_key": private_key,
        "fingerprint_sha256": fingerprint,
        "valid_from": _ensure_timezone(certificate.not_valid_before),
        "valid_to": _ensure_timezone(certificate.not_valid_after),
        "subject_cnpj": _normalize_cnpj(subject_cnpj),
    }
