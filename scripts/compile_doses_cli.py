# -*- coding: utf-8 -*-
"""CLI da compilação do Controle de doses PMO (para dynos one-off e depuração).

Sem flags roda em SIMULAÇÃO (nada é escrito). Use --apply para escrever e
--include-compiled para revisitar também as abas-dia já verdes.

Ex.: heroku run "python scripts/compile_doses_cli.py --include-compiled"
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from services.vacina_pmo_service import compile_controle_de_doses


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="escreve de verdade (padrão: simulação)")
    parser.add_argument(
        "--include-compiled", action="store_true", help="revisita também abas já compiladas (verdes)"
    )
    args = parser.parse_args()
    with app.app_context():
        result = compile_controle_de_doses(
            dry_run=not args.apply, include_compiled=args.include_compiled
        )
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
