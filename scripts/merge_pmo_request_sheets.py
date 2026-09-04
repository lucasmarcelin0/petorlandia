"""
merge_pmo_request_sheets.py
===========================
Reune na aba oficial de solicitacoes as linhas que cairam em abas duplicadas
da planilha da campanha PMO.

O QUE ACONTECEU
  A aba de solicitacoes foi renomeada na planilha ("Solicitacoes" ->
  "Solicitacoes de vacina"). O app procurava a aba pelo nome exato, nao
  encontrou e criou uma copia vazia com o nome antigo no fim da planilha. A
  partir dai toda solicitacao enviada em /vacina-pmo/solicitar foi gravada
  nessa copia -- some da aba que a equipe acompanha, mesmo tendo sido enviada
  com sucesso pelo morador.

QUANDO USAR
  A mesma reconciliacao ja roda sozinha no sync periodico do PMO (dyno
  ``scheduler``, a cada PMO_SYNC_INTERVAL_MINUTES). Este script serve para
  rodar na hora, ou para conferir com --dry-run o que seria movido.

Uso:
  python scripts/merge_pmo_request_sheets.py --dry-run
  python scripts/merge_pmo_request_sheets.py
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
    from services.vacina_pmo_service import reconcile_pmo_request_sheets

    prefix = "[DRY-RUN] " if dry_run else ""
    app = create_app()
    with app.app_context():
        result = reconcile_pmo_request_sheets(apply=not dry_run)

    log.info("Aba oficial de solicitacoes: %r", result["canonical"])
    if not result["duplicates"]:
        log.info("Nenhuma aba duplicada de solicitacoes. Nada a fazer.")
        return 0

    log.info("Abas duplicadas: %s", ", ".join(repr(t) for t in result["duplicates"]))
    log.info(
        "%s%d solicitacao(oes) movida(s), %d registro(s) local(is) reapontado(s).",
        prefix,
        result["moved"],
        result["repointed"],
    )
    if result["unmatched"]:
        log.warning(
            "%d linha(s) sem registro local: a aba duplicada nao foi limpa. "
            "Confira se este comando esta ligado ao banco de producao (DATABASE_URL).",
            result["unmatched"],
        )
    elif not dry_run and result["moved"]:
        log.info("Apague as abas duplicadas vazias a mao quando conferir a planilha.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra quantas linhas seriam movidas, sem escrever na planilha nem no banco.",
    )
    args = parser.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
