"""
backfill_pmo_tutor_contato.py
=============================
Conserta os dois campos que as contas criadas pela campanha PMO deixaram pela
metade e que so aparecem quando alguem abre a ficha do tutor:

1. ENDERECO
   O PMO gravava so ``User.address`` (texto livre, usado nas impressoes). A
   ficha do tutor le ``User.endereco``, que e o modelo estruturado -- por isso
   o endereco parecia "sumido". Aqui criamos o Endereco a partir do texto da
   visita, reaproveitando o mesmo parser e o mesmo geocode da otimizacao de
   rota. Com --geocode busca coordenada nova para quem ainda nao tem (uma
   chamada de rede por visita; sem a flag so usa o que ja esta em cache).

2. E-MAIL PROVISORIO
   ``pmo-<telefone>@petorlandia.local`` e identificador interno, nao e-mail da
   tutora. Sem ``email_is_placeholder`` a interface exibia esse endereco como
   contato real, montava mailto: para um dominio que nao existe e o "esqueci
   minha senha" tentava enviar e-mail para la.

Nao sobrescreve nada preenchido a mao: endereco corrigido na clinica e
e-mail real informado depois continuam como estao.

Uso:
  python scripts/backfill_pmo_tutor_contato.py --dry-run
  python scripts/backfill_pmo_tutor_contato.py
  python scripts/backfill_pmo_tutor_contato.py --geocode
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


def run(dry_run: bool = False, geocode: bool = False) -> int:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app_factory import create_app
    from extensions import db
    from models import PmoVaccinationVisit, User
    from models.usuarios import PMO_PROVISIONAL_EMAIL_DOMAIN
    from services.vacina_pmo_service import (
        _apply_visit_address,
        _pmo_geocode_visit,
    )

    app = create_app()
    with app.app_context():
        prefix = "[DRY-RUN] " if dry_run else ""
        stats = {
            "enderecos_criados": 0,
            "geocodes_novos": 0,
            "emails_marcados": 0,
        }

        # --- 1. Endereco estruturado -------------------------------------
        visits = (
            PmoVaccinationVisit.query
            .filter(PmoVaccinationVisit.tutor_user_id.isnot(None))
            .order_by(PmoVaccinationVisit.id)
            .all()
        )
        # Nao filtra por endereco_id vazio: _apply_visit_address tambem decide o
        # caso de tutor com mais de um endereco (vale o da visita mais recente,
        # o anterior vai para observacoes) e o de endereco corrigido a mao.
        for visit in visits:
            tutor = visit.tutor_user
            if tutor is None or not visit.address:
                continue

            if geocode and (visit.geocode_lat is None or visit.geocode_lng is None):
                try:
                    if _pmo_geocode_visit(visit):
                        stats["geocodes_novos"] += 1
                except Exception:
                    log.warning("Geocode falhou para a visita %s", visit.id, exc_info=True)

            if _apply_visit_address(tutor, visit):
                stats["enderecos_criados"] += 1
                log.info(
                    "%stutor id=%s '%s' endereco <- %r (endereco_id=%s)",
                    prefix, tutor.id, tutor.name, visit.address, tutor.endereco_id,
                )

        # --- 2. E-mail provisorio ----------------------------------------
        provisional = (
            User.query
            .filter(User.email.ilike(f"%@{PMO_PROVISIONAL_EMAIL_DOMAIN}"))
            .filter(User.email_is_placeholder.is_(False))
            .order_by(User.id)
            .all()
        )
        for user in provisional:
            stats["emails_marcados"] += 1
            log.info(
                "%stutor id=%s '%s' e-mail %s marcado como provisorio",
                prefix, user.id, user.name, user.email,
            )
            if not dry_run:
                user.email_is_placeholder = True

        if dry_run:
            db.session.rollback()
            log.info("[DRY-RUN] Nada foi gravado.")
        else:
            db.session.commit()

        log.info(
            "Enderecos criados: %s | Geocodes novos: %s | E-mails marcados: %s",
            stats["enderecos_criados"],
            stats["geocodes_novos"],
            stats["emails_marcados"],
        )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o que mudaria sem gravar nada.",
    )
    parser.add_argument(
        "--geocode",
        action="store_true",
        help="Busca coordenada para visitas sem cache (uma chamada de rede por visita).",
    )
    args = parser.parse_args()
    return run(dry_run=args.dry_run, geocode=args.geocode)


if __name__ == "__main__":
    raise SystemExit(main())
