"""Backfill do JSON `conteudo_estruturado` em medicamentos existentes.

Uso:
  python scripts/backfill_medicamentos_structured_content.py
  python scripts/backfill_medicamentos_structured_content.py --force --limit 200
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app, db  # noqa: E402
from models.base import Medicamento  # noqa: E402
from services.bulario import construir_conteudo_estruturado  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()

    atualizados = 0
    pulados = 0
    processados = 0

    with app.app_context():
        last_id = 0
        while True:
            query = (
                Medicamento.query
                .filter(Medicamento.id > last_id)
                .order_by(Medicamento.id.asc())
                .limit(args.batch_size)
            )
            if args.limit and args.limit > 0:
                restante = args.limit - processados
                if restante <= 0:
                    break
                query = query.limit(min(args.batch_size, restante))

            lote = query.all()
            if not lote:
                break

            for med in lote:
                atual = getattr(med, "conteudo_estruturado", None)
                if atual and not args.force:
                    pulados += 1
                    processados += 1
                    last_id = med.id
                    continue

                estruturado = construir_conteudo_estruturado(
                    observacoes=med.observacoes,
                )
                if not any([
                    estruturado["indicacoes"]["itens"],
                    estruturado["contraindicacoes"]["itens"],
                    estruturado["efeitos_adversos"]["itens"],
                    estruturado["advertencias"]["itens"],
                    estruturado["interacoes"]["itens"],
                ]):
                    pulados += 1
                    processados += 1
                    last_id = med.id
                    continue

                med.conteudo_estruturado = estruturado
                atualizados += 1
                processados += 1
                last_id = med.id

            db.session.commit()
            print(f"Processados: {processados} | Atualizados: {atualizados} | Pulados: {pulados}")

    print(
        f"Backfill concluído. Atualizados: {atualizados}. "
        f"Pulados: {pulados}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
