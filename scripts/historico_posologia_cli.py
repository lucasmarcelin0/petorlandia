# -*- coding: utf-8 -*-
"""Pesquisa o histórico de prescrições por termo de medicamento (só leitura).

Útil para curar protocolos a partir do que o veterinário realmente receitou.

Ex.: heroku run "python scripts/historico_posologia_cli.py doxiciclina"
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from models import Prescricao


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("termo", help="parte do nome do medicamento")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    with app.app_context():
        rows = (
            Prescricao.query.filter(Prescricao.medicamento.ilike(f"%{args.termo}%"))
            .order_by(Prescricao.data_prescricao.desc())
            .limit(args.limit)
            .all()
        )
        combos: Counter = Counter()
        for row in rows:
            data = row.data_prescricao.strftime("%d/%m/%Y") if row.data_prescricao else "-"
            print(
                f"{data} | {row.medicamento} | dose: {row.dosagem or '-'} | "
                f"freq: {row.frequencia or '-'} | dur: {row.duracao or '-'}"
            )
            combos[(row.dosagem or "-", row.frequencia or "-", row.duracao or "-")] += 1
        print(f"\nTotal: {len(rows)} receita(s). Combinações mais comuns:")
        for (dose, freq, dur), count in combos.most_common(5):
            print(f"  {count}x → dose: {dose} | freq: {freq} | dur: {dur}")


if __name__ == "__main__":
    main()
