"""
backfill_pmo_animais_adotados.py
================================
Forca `modo='adotado'` para os animais criados automaticamente pela campanha
PMO (vinculados em PmoVaccinationAnimal.animal_id). Sem este ajuste, os animais
aparecem nas listagens publicas de adocao.

Uso:
  python scripts/backfill_pmo_animais_adotados.py --dry-run
  python scripts/backfill_pmo_animais_adotados.py
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


def run(dry_run: bool = False) -> int:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app_factory import create_app
    from extensions import db
    from models import Animal, PmoVaccinationAnimal

    app = create_app()
    with app.app_context():
        query = (
            Animal.query
            .join(PmoVaccinationAnimal, PmoVaccinationAnimal.animal_id == Animal.id)
            .filter(Animal.modo != 'adotado')
        )

        scanned = 0
        changed = 0
        for animal in query.yield_per(200):
            scanned += 1
            old_modo = animal.modo
            animal.modo = 'adotado'
            changed += 1
            log.info(
                "%s animal id=%s nome='%s' modo: %s -> adotado",
                "[DRY-RUN] Atualizaria" if dry_run else "Atualizado",
                animal.id,
                animal.name,
                old_modo,
            )

        if dry_run:
            db.session.rollback()
            log.info("(modo --dry-run: nenhuma alteracao foi gravada)")
        else:
            db.session.commit()
            log.info("Commit realizado.")

        log.info("=" * 55)
        log.info("Animais PMO avaliados : %d", scanned)
        log.info("Animais PMO alterados : %d", changed)
        log.info("=" * 55)

    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Backfill: marca animais criados pela campanha PMO como adotados'
    )
    parser.add_argument('--dry-run', action='store_true', help='Simula sem gravar no banco')
    args = parser.parse_args()
    raise SystemExit(run(dry_run=args.dry_run))
