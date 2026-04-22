"""Criptografia em repouso de FiscalDocument.xml_signed e xml_authorized.

Razão: esses XMLs têm CPF/CNPJ do tomador, valores e assinatura digital
do emissor. Dump de backup vazado = base fiscal inteira exposta. A
criptografia é por clínica (chave derivada de FISCAL_MASTER_KEY + clinic_id),
então mesmo se o atacante ler só o banco, precisa da master key + saber que
clínica cada linha pertence.

Os testes abaixo garantem:
  1. Round-trip: setar plain -> ler plain, mas o blob no disco é cipher.
  2. Idempotência: salvar um valor já cifrado não dupla-envelopa.
  3. Isolamento por clínica: blob da clínica A não abre com chave da B.
  4. InvalidToken (legado plain no banco) não levanta — retorna como veio,
     permitindo migração gradual via backfill script.
"""
from __future__ import annotations

import pytest

from extensions import db
from models import FiscalDocument, FiscalDocumentStatus, FiscalDocumentType, FiscalEmitter
from security.crypto import (
    FERNET_PREFIX,
    clear_crypto_cache,
    decrypt_text_for_clinic,
    encrypt_text_for_clinic,
    looks_encrypted_text,
)


def _make_emitter(clinic_id: int, cnpj: str) -> FiscalEmitter:
    emitter = FiscalEmitter(
        clinic_id=clinic_id,
        cnpj=cnpj,
        razao_social="Clinica Cripto",
    )
    db.session.add(emitter)
    db.session.commit()
    return emitter


def _make_document(emitter: FiscalEmitter) -> FiscalDocument:
    doc = FiscalDocument(
        emitter_id=emitter.id,
        clinic_id=emitter.clinic_id,
        doc_type=FiscalDocumentType.NFSE,
        status=FiscalDocumentStatus.DRAFT,
    )
    db.session.add(doc)
    db.session.flush()
    return doc


def test_xml_signed_round_trip_e_cifra_em_repouso(app, monkeypatch):
    """Atribuir plain no .xml_signed persiste cipher; leitura volta plain."""
    monkeypatch.setenv("FISCAL_MASTER_KEY", "test-master-key-signed")
    clear_crypto_cache()

    with app.app_context():
        emitter = _make_emitter(clinic_id=1, cnpj="00.000.000/0001-00")
        doc = _make_document(emitter)

        plain = "<?xml version='1.0'?><NFS-e><Valor>100.00</Valor></NFS-e>"
        doc.xml_signed = plain
        db.session.commit()

        # O que está guardado na coluna crua deve começar com FERNET_PREFIX.
        assert doc._xml_signed.startswith(FERNET_PREFIX), (
            "xml_signed não foi cifrado: o blob não tem prefixo Fernet."
        )
        assert looks_encrypted_text(doc._xml_signed)

        # Leitura via .xml_signed retorna o plaintext original.
        assert doc.xml_signed == plain


def test_xml_signed_idempotente_nao_dupla_envelopa(app, monkeypatch):
    """Salvar um valor já cifrado não cifra de novo — senão o setter em
    update de formulário web geraria camadas infinitas."""
    monkeypatch.setenv("FISCAL_MASTER_KEY", "test-master-key-signed2")
    clear_crypto_cache()

    with app.app_context():
        emitter = _make_emitter(clinic_id=2, cnpj="00.000.000/0001-01")
        doc = _make_document(emitter)

        plain = "<x/>"
        cipher = encrypt_text_for_clinic(emitter.clinic_id, plain)

        doc.xml_signed = cipher  # já cifrado
        db.session.commit()

        # O blob no banco deve ser exatamente o mesmo cipher passado.
        assert doc._xml_signed == cipher
        # E leitura retorna o plaintext — confirma que não foi re-cifrado.
        assert doc.xml_signed == plain


def test_xml_signed_isolamento_entre_clinicas(app, monkeypatch):
    """Cipher da clínica A não pode ser decifrado com chave da B.
    Isso é o ponto central de usar derivação por clinic_id."""
    monkeypatch.setenv("FISCAL_MASTER_KEY", "test-master-key-iso")
    clear_crypto_cache()

    with app.app_context():
        emitter_a = _make_emitter(clinic_id=10, cnpj="00.000.000/0001-10")
        doc_a = _make_document(emitter_a)
        doc_a.xml_signed = "<segredo-de-A/>"
        db.session.commit()

        # Blob cru da A. Tentar decifrar com clinic_id=99 deve levantar.
        raw = doc_a._xml_signed
        from cryptography.fernet import InvalidToken

        with pytest.raises(InvalidToken):
            decrypt_text_for_clinic(99, raw)


def test_xml_signed_plain_legado_nao_quebra(app, monkeypatch):
    """Dados pré-migração podem ter plaintext. Getter não deve levantar:
    retorna como veio (e o backfill script migra depois)."""
    monkeypatch.setenv("FISCAL_MASTER_KEY", "test-master-key-legacy")
    clear_crypto_cache()

    with app.app_context():
        emitter = _make_emitter(clinic_id=3, cnpj="00.000.000/0001-02")
        doc = _make_document(emitter)

        # Bypass do setter: escreve plaintext direto na coluna interna
        # para simular um registro criado antes da migração.
        doc._xml_signed = "<nfse-plain-legado/>"
        db.session.commit()

        # Getter não deve explodir — só devolver o plaintext.
        assert doc.xml_signed == "<nfse-plain-legado/>"


def test_xml_authorized_continua_cifrando(app, monkeypatch):
    """Regressão: ao refatorar xml_signed não pode ter quebrado o
    comportamento preexistente de xml_authorized."""
    monkeypatch.setenv("FISCAL_MASTER_KEY", "test-master-key-auth")
    clear_crypto_cache()

    with app.app_context():
        emitter = _make_emitter(clinic_id=4, cnpj="00.000.000/0001-03")
        doc = _make_document(emitter)

        plain = "<autorizado/>"
        doc.xml_authorized = plain
        db.session.commit()

        assert doc._xml_authorized.startswith(FERNET_PREFIX)
        assert doc.xml_authorized == plain


def test_xml_authorized_sem_clinica_falha_em_vez_de_plaintext(monkeypatch):
    monkeypatch.setenv("FISCAL_MASTER_KEY", "test-master-key-no-clinic")
    clear_crypto_cache()

    doc = FiscalDocument(
        emitter_id=1,
        doc_type=FiscalDocumentType.NFSE,
        status=FiscalDocumentStatus.DRAFT,
    )

    with pytest.raises(ValueError, match="clinic_id"):
        doc.xml_authorized = "<xml sensivel/>"
