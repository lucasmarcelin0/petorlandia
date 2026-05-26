"""
backfill_pmo_carteirinha.py
===========================
Backfill para preencher as lacunas da carteirinha de vacinacao PMO:

- Copia visit.address para o User.address do tutor (apenas quando vazio).
- Atualiza Vacina aplicada da campanha PMO: aplicada_por (vet da campanha),
  lote e fabricante.
- Ajusta fabricante das doses planejadas (Reforco PMO) para o mesmo padrao.

Uso:
  python scripts/backfill_pmo_carteirinha.py --dry-run
  python scripts/backfill_pmo_carteirinha.py
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
    from models import PmoVaccinationVisit, Vacina
    from services.vacina_pmo_service import (
        PMO_CAMPAIGN_VET_EMAIL,
        PMO_VACCINE_FABRICANTE,
        PMO_VACCINE_LOTE,
        _campaign_vet_user_id,
    )

    app = create_app()
    with app.app_context():
        vet_id = _campaign_vet_user_id()
        if not vet_id:
            log.error("Veterinario da campanha (%s) nao encontrado.", PMO_CAMPAIGN_VET_EMAIL)
            return 2

        addresses_updated = 0
        for visit in PmoVaccinationVisit.query.all():
            tutor = visit.tutor_user
            if tutor and visit.address and not tutor.address:
                log.info(
                    "%s tutor id=%s '%s' address -> %r",
                    "[DRY-RUN]" if dry_run else "Atualizado",
                    tutor.id,
                    tutor.name,
                    visit.address,
                )
                tutor.address = visit.address
                addresses_updated += 1

        vacinas_applied = (
            Vacina.query
            .filter(Vacina.tipo == "Campanha PMO", Vacina.aplicada.is_(True))
            .all()
        )
        applied_updated = 0
        for vac in vacinas_applied:
            changed = []
            if not vac.aplicada_por:
                vac.aplicada_por = vet_id
                changed.append("aplicada_por")
            if not vac.lote:
                vac.lote = PMO_VACCINE_LOTE
                changed.append("lote")
            if not vac.fabricante or vac.fabricante == "Prefeitura de Orlandia":
                vac.fabricante = PMO_VACCINE_FABRICANTE
                changed.append("fabricante")
            if changed:
                applied_updated += 1
                log.info(
                    "%s vacina id=%s campos=%s",
                    "[DRY-RUN]" if dry_run else "Atualizado",
                    vac.id,
                    ",".join(changed),
                )

        booster_updated = 0
        boosters = Vacina.query.filter(Vacina.tipo == "Reforco PMO").all()
        for vac in boosters:
            if not vac.fabricante or vac.fabricante == "Prefeitura de Orlandia":
                vac.fabricante = PMO_VACCINE_FABRICANTE
                booster_updated += 1
                log.info(
                    "%s reforco id=%s fabricante",
                    "[DRY-RUN]" if dry_run else "Atualizado",
                    vac.id,
                )

        if dry_run:
            db.session.rollback()
            log.info("(modo --dry-run: nenhuma alteracao foi gravada)")
        else:
            db.session.commit()
            log.info("Commit realizado.")

        log.info("=" * 55)
        log.info("Enderecos de tutores preenchidos : %d", addresses_updated)
        log.info("Vacinas aplicadas atualizadas    : %d", applied_updated)
        log.info("Reforcos atualizados             : %d", booster_updated)
        log.info("Vet da campanha (user_id)        : %d", vet_id)
        log.info("=" * 55)

    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Backfill da carteirinha PMO (enderecos, vet, lote, fabricante)'
    )
    parser.add_argument('--dry-run', action='store_true', help='Simula sem gravar no banco')
    args = parser.parse_args()
    raise SystemExit(run(dry_run=args.dry_run))
