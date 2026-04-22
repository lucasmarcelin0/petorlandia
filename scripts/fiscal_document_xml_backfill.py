"""Backfill de criptografia dos XMLs em FiscalDocument.

Registros criados antes da Fase 1.3 têm xml_signed e xml_authorized em
plaintext. Este script migra-os para cifra por clínica (Fernet com chave
derivada de FISCAL_MASTER_KEY + clinic_id).

É SEGURO rodar múltiplas vezes: só mexe em linhas que ainda não começam
com o prefixo Fernet.

Uso:
    python scripts/fiscal_document_xml_backfill.py
    python scripts/fiscal_document_xml_backfill.py --dry-run
    python scripts/fiscal_document_xml_backfill.py --clinic-id 123

Por que "--clinic-id" existe:
    Se o backfill travar num registro corrompido, rodar clínica por
    clínica permite isolar o problema sem bloquear o resto do tenant.
"""
from __future__ import annotations

import argparse
import logging

from app import app, db
from models import FiscalDocument
from security.crypto import (
    MissingMasterKeyError,
    encrypt_text_for_clinic,
    looks_encrypted_text,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# As colunas internas (com prefixo _) são o BLOB cru no banco.
# Escrever nelas direto evita passar pelo setter (que é idempotente mas
# teria que instanciar o objeto inteiro com clinic_id antes).
XML_COLUMNS = ("_xml_signed", "_xml_authorized")


def backfill(dry_run: bool = False, clinic_id: int | None = None) -> int:
    with app.app_context():
        query = FiscalDocument.query
        if clinic_id is not None:
            query = query.filter(FiscalDocument.clinic_id == clinic_id)
        documents = query.all()

        total = len(documents)
        updated_docs = 0
        updated_fields = 0

        for doc in documents:
            if not doc.clinic_id:
                logger.warning(
                    "FiscalDocument id=%s sem clinic_id — pulando (não temos "
                    "chave de criptografia).", doc.id,
                )
                continue

            changed = False
            for column in XML_COLUMNS:
                value = getattr(doc, column)
                if not value or looks_encrypted_text(value):
                    continue
                try:
                    encrypted = encrypt_text_for_clinic(doc.clinic_id, value)
                except MissingMasterKeyError:
                    logger.error(
                        "FISCAL_MASTER_KEY ausente — aborte, configure a "
                        "chave, e re-rode. Nenhuma alteração foi commitada."
                    )
                    db.session.rollback()
                    return 1
                setattr(doc, column, encrypted)
                updated_fields += 1
                changed = True

            if changed:
                updated_docs += 1

        if dry_run:
            db.session.rollback()
            logger.info(
                "[DRY-RUN] %s documentos inspecionados, %s seriam atualizados "
                "(%s campos XML cifrados).",
                total, updated_docs, updated_fields,
            )
        else:
            db.session.commit()
            logger.info(
                "%s documentos inspecionados, %s atualizados "
                "(%s campos XML cifrados).",
                total, updated_docs, updated_fields,
            )
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Executa sem persistir alterações.")
    parser.add_argument("--clinic-id", type=int, default=None,
                        help="Processa apenas a clínica informada.")
    args = parser.parse_args()
    raise SystemExit(backfill(dry_run=args.dry_run, clinic_id=args.clinic_id))


if __name__ == "__main__":
    main()
