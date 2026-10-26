"""
merge_tutor_accounts.py
=======================
Junta duas contas que sao a mesma pessoa. Move TUDO que aponta para a conta de
origem (animais, consultas, visitas PMO, pagamentos, mensagens...) para a conta
que fica, e preserva na ficha o que a origem tinha de diferente.

Por que e generico em vez de uma lista de tabelas: existem 104 chaves
estrangeiras apontando para user.id. Uma lista escrita a mao ficaria
desatualizada no primeiro model novo e deixaria registro orfao sem avisar. Aqui
as colunas sao descobertas do metadata do SQLAlchemy, entao tabela nova entra
sozinha.

Colisao de unicidade: ha constraints como oauth_consent(user_id, client_id) e
medicamento_favorito(user_id, medicamento_id). Se a conta que fica ja tem a
linha equivalente, mover geraria IntegrityError -- nesses casos a linha da
origem e descartada (e um duplicado por definicao), e o script informa quantas.

O tutor de origem NAO e apagado por padrao. Ele fica sem vinculos, marcado nas
observacoes, para voce conferir antes. Use --delete-source quando tiver certeza.

Uso:
  python scripts/merge_tutor_accounts.py --from 123 --into 456 --dry-run
  python scripts/merge_tutor_accounts.py --from 123 --into 456
  python scripts/merge_tutor_accounts.py --from 123 --into 456 --delete-source

Para descobrir os ids:
  python scripts/audit_duplicate_phone_accounts.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# O núcleo mora em services/tutor_merge.py (usado também pela tela do tutor).
# Reexportado aqui para manter ``from scripts.merge_tutor_accounts import
# merge_accounts`` funcionando.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services import tutor_merge as _core  # noqa: E402
from services.tutor_merge import (  # noqa: E402,F401
    _INHERITABLE_FIELDS,
    _rows_colliding_with_target,
    _unique_companion_groups,
    _user_referencing_columns,
    merge_accounts,
)

# Mensagens do núcleo saem no stdout do script, como antes.
_core.log.setLevel(logging.INFO)


def run(
    source_id: int,
    target_id: int,
    dry_run: bool = False,
    delete_source: bool = False,
) -> int:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app_factory import create_app

    app = create_app()
    with app.app_context():
        return merge_accounts(
            source_id=source_id,
            target_id=target_id,
            dry_run=dry_run,
            delete_source=delete_source,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source_id", type=int, required=True,
                        help="Id da conta que sera esvaziada.")
    parser.add_argument("--into", dest="target_id", type=int, required=True,
                        help="Id da conta que fica.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostra o que mudaria sem gravar nada.")
    parser.add_argument("--delete-source", action="store_true",
                        help="Apaga a conta de origem ao final (irreversivel).")
    args = parser.parse_args()
    return run(
        source_id=args.source_id,
        target_id=args.target_id,
        dry_run=args.dry_run,
        delete_source=args.delete_source,
    )


if __name__ == "__main__":
    raise SystemExit(main())
