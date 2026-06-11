# -*- coding: utf-8 -*-
"""Imprime o Controle de frascos PMO reconstruído da "Controle de doses".

Só leitura — útil para validar a linha do tempo retroativamente.

Ex.: heroku run "python scripts/frascos_ledger_cli.py"
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from services.vacina_pmo_service import get_pmo_frascos_ledger


def main() -> None:
    with app.app_context():
        result = get_pmo_frascos_ledger()
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
