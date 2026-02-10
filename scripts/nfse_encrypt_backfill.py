"""Backfill de criptografia dos campos NFS-e em Clinica.

Uso:
    python scripts/nfse_encrypt_backfill.py
    python scripts/nfse_encrypt_backfill.py --dry-run
    python scripts/nfse_encrypt_backfill.py --clinic-id 123
"""
import argparse
import logging

from app import app, db
from models import Clinica
from security.crypto import MissingMasterKeyError, encrypt_text, looks_encrypted_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NFSE_FIELDS = [
    "nfse_username",
    "nfse_password",
    "nfse_cert_path",
    "nfse_cert_password",
    "nfse_token",
]


def backfill_nfse_encryption(dry_run: bool = False, clinic_id: int | None = None) -> int:
    with app.app_context():
        query = Clinica.query
        if clinic_id:
            query = query.filter(Clinica.id == clinic_id)
        clinics = query.all()
        total = len(clinics)
        updated = 0

        for clinic in clinics:
            changed = False
            for field_name in NFSE_FIELDS:
                value = clinic.get_nfse_encrypted(field_name)
                if not value:
                    continue
                if looks_encrypted_text(value):
                    continue
                try:
                    encrypted = encrypt_text(value)
                except MissingMasterKeyError:
                    logger.error(
                        "FISCAL_MASTER_KEY não configurada. Aborte a execução e configure a chave."
                    )
                    db.session.rollback()
                    return 1
                setattr(clinic, field_name, encrypted)
                changed = True
            if changed:
                updated += 1
                if not dry_run:
                    db.session.add(clinic)

        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()

        logger.info(
            "Backfill concluído. Total clínicas: %s. Atualizadas: %s. Dry-run: %s",
            total,
            updated,
            dry_run,
        )
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Executa sem persistir alterações.",
    )
    parser.add_argument(
        "--clinic-id",
        type=int,
        default=None,
        help="Processa apenas a clínica informada.",
    )
    args = parser.parse_args()

    raise SystemExit(backfill_nfse_encryption(dry_run=args.dry_run, clinic_id=args.clinic_id))


if __name__ == "__main__":
    main()
