"""
backfill_todos_animais_adotados.py
=================================
Força `modo='adotado'` para todos os animais (com filtros opcionais).

Uso:
  python scripts/backfill_todos_animais_adotados.py --dry-run
  python scripts/backfill_todos_animais_adotados.py
  python scripts/backfill_todos_animais_adotados.py --clinic-id 123
  python scripts/backfill_todos_animais_adotados.py --include-removed
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def run(dry_run: bool = False, clinic_id: int | None = None, include_removed: bool = False) -> int:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app_factory import create_app
    from extensions import db
    from models.base import Animal

    app = create_app()
    with app.app_context():
        query = Animal.query
        if clinic_id is not None:
            query = query.filter_by(clinica_id=clinic_id)
        if not include_removed:
            query = query.filter(Animal.removido_em.is_(None))

        scanned = 0
        changed = 0

        for animal in query.yield_per(200):
            scanned += 1
            if animal.modo == 'adotado':
                continue
            old_modo = animal.modo
            animal.modo = 'adotado'
            changed += 1
            log.info("%s animal id=%s nome='%s' modo: %s -> adotado",
                     "[DRY-RUN] Atualizaria" if dry_run else "✔ Atualizado",
                     animal.id,
                     animal.name,
                     old_modo)

        if dry_run:
            db.session.rollback()
            log.info("(modo --dry-run: nenhuma alteração foi gravada)")
        else:
            db.session.commit()
            log.info("✅ Commit realizado.")

        log.info("=" * 55)
        log.info("Animais avaliados   : %d", scanned)
        log.info("Animais alterados   : %d", changed)
        log.info("Clinic filter       : %s", clinic_id if clinic_id is not None else "(todas)")
        log.info("Include removidos   : %s", include_removed)
        log.info("=" * 55)

    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backfill para marcar todos os animais como adotados')
    parser.add_argument('--dry-run', action='store_true', help='Simula sem gravar no banco')
    parser.add_argument('--clinic-id', type=int, default=None, help='Restringe a uma clínica')
    parser.add_argument('--include-removed', action='store_true', help='Inclui animais removidos')
    args = parser.parse_args()
    raise SystemExit(run(dry_run=args.dry_run, clinic_id=args.clinic_id, include_removed=args.include_removed))
