"""Remove apresentações incorretas de Virbac (Contralac 5 e 20) do registro
de Metergolina.

Essas apresentações (5 mg e 20 mg da Virbac) são na verdade Contralac
(cabergolina), não Sec Lac (metergolina). Foram cadastradas por engano no
medication de metergolina, fazem a metergolina aparecer com concentrações
inexistentes e quebram a seleção automática de apresentação.

IDs confirmados em produção via inspect_metergolina.py:
  AP 1763 — 5 mg comprimido (Virbac)
  AP 1764 — 20 mg comprimido (Virbac)

Execute via:
  heroku run python scripts/fix_metergolina_apresentacoes.py           # dry-run
  heroku run python scripts/fix_metergolina_apresentacoes.py --apply   # aplica
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from extensions import db
from models.base import ApresentacaoMedicamento

IDS_INCORRETOS = [1763, 1764]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Apaga de verdade (padrão: só simula)")
    args = parser.parse_args()

    with app.app_context():
        for ap_id in IDS_INCORRETOS:
            ap = ApresentacaoMedicamento.query.get(ap_id)
            if not ap:
                print(f"  AP id={ap_id}: NÃO ENCONTRADA (já removida?)")
                continue
            print(
                f"  AP id={ap_id}: {ap.concentracao_valor!r} {ap.concentracao_unidade!r} "
                f"{ap.forma!r} fab={ap.fabricante!r} med_id={ap.medicamento_id!r}"
            )
            if args.apply:
                db.session.delete(ap)

        if args.apply:
            db.session.commit()
            print("\n✓ Apresentações removidas.")
        else:
            print("\n⚠  SIMULAÇÃO — rode com --apply para remover de verdade.")


if __name__ == "__main__":
    main()
