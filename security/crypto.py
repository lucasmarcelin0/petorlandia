"""Cryptography helpers for fiscal certificates."""

import base64
import hashlib
import os
from functools import lru_cache
from typing import Union

from cryptography.fernet import Fernet


class MissingMasterKeyError(RuntimeError):
    """Raised when the master key is not configured."""

FERNET_PREFIX = "gAAAA"


def looks_encrypted_text(value: str) -> bool:
    return isinstance(value, str) and value.startswith(FERNET_PREFIX)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    master_key = _get_master_key()
    derived = hashlib.sha256(master_key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(derived)
    return Fernet(fernet_key)


def _get_master_key() -> str:
    master_key = (os.getenv("FISCAL_MASTER_KEY") or "").strip()
    if not master_key:
        raise MissingMasterKeyError(
            "FISCAL_MASTER_KEY must be set to encrypt fiscal secrets."
        )
    return master_key


@lru_cache(maxsize=128)
def _get_clinic_fernet(clinica_id: Union[int, str]) -> Fernet:
    if clinica_id is None:
        raise ValueError("clinica_id must be informed for clinic encryption.")
    master_key = _get_master_key()
    seed = f"{master_key}:{clinica_id}".encode("utf-8")
    derived = hashlib.sha256(seed).digest()
    fernet_key = base64.urlsafe_b64encode(derived)
    return Fernet(fernet_key)


def encrypt_bytes(data: bytes) -> bytes:
    return _get_fernet().encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    return _get_fernet().decrypt(data)


def encrypt_bytes_for_clinic(clinica_id: Union[int, str], data: bytes) -> bytes:
    return _get_clinic_fernet(clinica_id).encrypt(data)


def decrypt_bytes_for_clinic(clinica_id: Union[int, str], data: bytes) -> bytes:
    return _get_clinic_fernet(clinica_id).decrypt(data)


def encrypt_text(text: str) -> str:
    return encrypt_bytes(text.encode("utf-8")).decode("utf-8")


def decrypt_text(text: str) -> str:
    return decrypt_bytes(text.encode("utf-8")).decode("utf-8")


def encrypt_text_for_clinic(clinica_id: Union[int, str], text: str) -> str:
    if looks_encrypted_text(text):
        return text
    return encrypt_bytes_for_clinic(clinica_id, text.encode("utf-8")).decode("utf-8")


def decrypt_text_for_clinic(clinica_id: Union[int, str], text: str) -> str:
    if not looks_encrypted_text(text):
        return text
    return decrypt_bytes_for_clinic(clinica_id, text.encode("utf-8")).decode("utf-8")


def clear_crypto_cache() -> None:
    _get_fernet.cache_clear()
    _get_clinic_fernet.cache_clear()
