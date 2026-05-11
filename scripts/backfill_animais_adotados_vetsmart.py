"""
backfill_animais_adotados_vetsmart.py
====================================
Corrige animais já migrados do VetSmart que ficaram com modo incorreto
(ex.: "doação") e devem ser tratados como "adotado".

A rotina lê checkpoints locais em scripts/vetsmart_raw:
  - animais.json
  - tutores.json

Estratégia de match:
  1) Resolve o tutor do VetSmart (objectId) para um User no banco (cpf ou e-mail)
  2) Procura Animal por (name, user_id) e opcionalmente clinica_id

Uso:
  python scripts/backfill_animais_adotados_vetsmart.py --dry-run
  python scripts/backfill_animais_adotados_vetsmart.py
  python scripts/backfill_animais_adotados_vetsmart.py --clinic-id 123
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

RAW_DIR = Path(__file__).parent / "vetsmart_raw"
RAW_ANIMAIS = RAW_DIR / "animais.json"
RAW_TUTORES = RAW_DIR / "tutores.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):
        if v.get("__type") == "Date":
            return v.get("iso", "")
        return str(v)
    return str(v)


def _norm_cpf(cpf: str) -> str:
    return cpf.replace(".", "").replace("-", "").strip()


def _is_alive(vs_animal: dict) -> bool:
    deceased_val = _str(vs_animal.get("deceased") or "0").strip()
    return deceased_val not in ("1", "true", "True", "sim")


def run(dry_run: bool = False, clinic_id: int | None = None):
    missing = [str(p) for p in (RAW_ANIMAIS, RAW_TUTORES) if not p.exists()]
    if missing:
        for f in missing:
            log.error("Arquivo não encontrado: %s", f)
        return 1

    animais = json.loads(RAW_ANIMAIS.read_text(encoding="utf-8"))
    tutores = json.loads(RAW_TUTORES.read_text(encoding="utf-8"))

    tutor_by_vs_id = {
        t.get("objectId"): t
        for t in tutores
        if isinstance(t, dict) and t.get("objectId")
    }

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app_factory import create_app
    from extensions import db
    from models.base import Animal, User

    app = create_app()
    with app.app_context():
        scanned = 0
        updated = 0
        no_tutor_match = 0
        no_animal_match = 0
        already_ok = 0

        for vs_animal in animais:
            if not isinstance(vs_animal, dict):
                continue

            scanned += 1
            name = _str(vs_animal.get("name") or vs_animal.get("nome") or vs_animal.get("petName")).strip()
            if not name:
                continue

            tutor_ptr = vs_animal.get("tutor") or vs_animal.get("client") or vs_animal.get("owner") or {}
            tutor_vs_id = tutor_ptr.get("objectId") if isinstance(tutor_ptr, dict) else None
            tutor_raw = tutor_by_vs_id.get(tutor_vs_id) if tutor_vs_id else None

            if not tutor_raw:
                no_tutor_match += 1
                log.warning("⚠ Tutor VetSmart não encontrado para animal '%s' (vs_tutor=%s)", name, tutor_vs_id)
                continue

            cpf = _norm_cpf(_str(tutor_raw.get("cpf") or "")) or None
            email = _str(tutor_raw.get("email") or tutor_raw.get("ownerEmail") or "").lower().strip() or None

            user = None
            if cpf:
                user = User.query.filter_by(cpf=cpf).first()
            if not user and email:
                user = User.query.filter_by(email=email).first()

            if not user:
                no_tutor_match += 1
                log.warning("⚠ Sem User para tutor '%s' (cpf=%s, email=%s)", tutor_raw.get("name"), cpf, email)
                continue

            query = Animal.query.filter_by(name=name, user_id=user.id)
            if clinic_id is not None:
                query = query.filter_by(clinica_id=clinic_id)
            animal = query.first()

            if not animal:
                no_animal_match += 1
                log.warning("⚠ Sem Animal para nome='%s' user_id=%s", name, user.id)
                continue

            target_alive = _is_alive(vs_animal)
            target_status = "ativo" if target_alive else "inativo"

            changed = False
            if animal.modo != "adotado":
                animal.modo = "adotado"
                changed = True
            if animal.status != target_status:
                animal.status = target_status
                changed = True
            if animal.is_alive != target_alive:
                animal.is_alive = target_alive
                changed = True

            if changed:
                updated += 1
                if dry_run:
                    db.session.rollback()
                    log.info("[DRY-RUN] Atualizaria animal id=%s nome='%s' para modo=adotado", animal.id, animal.name)
                else:
                    log.info("✔ Atualizado animal id=%s nome='%s'", animal.id, animal.name)
            else:
                already_ok += 1

        if not dry_run:
            db.session.commit()
            log.info("\n✅ Commit realizado.")

        log.info("=" * 55)
        log.info("Animais lidos            : %d", scanned)
        log.info("Animais atualizados      : %d", updated)
        log.info("Já estavam corretos      : %d", already_ok)
        log.info("Sem match de tutor/User  : %d", no_tutor_match)
        log.info("Sem match de animal      : %d", no_animal_match)
        log.info("=" * 55)
        if dry_run:
            log.info("(modo --dry-run: nenhuma alteração foi gravada)")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill do modo adotado para animais migrados do VetSmart")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem gravar no banco")
    parser.add_argument("--clinic-id", type=int, default=None, help="Restringe atualização a uma clínica")
    args = parser.parse_args()
    raise SystemExit(run(dry_run=args.dry_run, clinic_id=args.clinic_id))
