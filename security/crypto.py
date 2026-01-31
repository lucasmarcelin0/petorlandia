"""Cryptography helpers for fiscal certificates."""

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet


class MissingMasterKeyError(RuntimeError):
    """Raised when the master key is not configured."""


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    master_key = (os.getenv("FISCAL_MASTER_KEY") or "").strip()
    if not master_key:
        raise MissingMasterKeyError(
            "FISCAL_MASTER_KEY must be set to encrypt fiscal secrets."
        )
    derived = hashlib.sha256(master_key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(derived)
    return Fernet(fernet_key)


def encrypt_bytes(data: bytes) -> bytes:
    return _get_fernet().encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    return _get_fernet().decrypt(data)


def encrypt_text(text: str) -> str:
    return encrypt_bytes(text.encode("utf-8")).decode("utf-8")


def decrypt_text(text: str) -> str:
    return decrypt_bytes(text.encode("utf-8")).decode("utf-8")
