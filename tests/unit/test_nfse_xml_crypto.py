import pytest
from cryptography.fernet import InvalidToken

from models import NfseXml
from security.crypto import (
    clear_crypto_cache,
    decrypt_text_for_clinic,
    encrypt_text_for_clinic,
)


def test_encrypt_decrypt_text_for_clinic_roundtrip(monkeypatch):
    monkeypatch.setenv("FISCAL_MASTER_KEY", "test-master-key")
    clear_crypto_cache()

    payload = "<xml>conteudo</xml>"
    encrypted = encrypt_text_for_clinic(1, payload)

    assert encrypted != payload
    assert decrypt_text_for_clinic(1, encrypted) == payload
    with pytest.raises(InvalidToken):
        decrypt_text_for_clinic(2, encrypted)


def test_nfse_xml_get_plaintext(monkeypatch):
    monkeypatch.setenv("FISCAL_MASTER_KEY", "test-master-key")
    clear_crypto_cache()

    payload = "<xml>retorno</xml>"
    encrypted = encrypt_text_for_clinic(5, payload)
    record = NfseXml(
        clinica_id=5,
        nfse_issue_id=1,
        tipo="emitir_envio",
        xml=encrypted,
    )

    assert record.get_xml_plaintext() == payload
