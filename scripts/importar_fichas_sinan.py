"""Importa complementos estruturados de fichas SINAN a partir de JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app
from services.sfa_service import importar_fichas_sinan_estruturadas


def _read_payload(source: str):
    if source == "-":
        return json.load(sys.stdin)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inclui ou complementa fichas SINAN estruturadas sem imprimir dados pessoais."
    )
    parser.add_argument("--input", required=True, help="Arquivo JSON ou '-' para entrada padrao.")
    parser.add_argument("--dry-run", action="store_true", help="Valida e desfaz todas as alteracoes.")
    args = parser.parse_args()

    with app.app_context():
        summary = importar_fichas_sinan_estruturadas(
            _read_payload(args.input),
            dry_run=args.dry_run,
        )

    safe_summary = {
        "recebidos": summary["recebidos"],
        "criados": summary["criados"],
        "atualizados": summary["atualizados"],
        "revisar": summary["revisar"],
        "dry_run": summary["dry_run"],
        "itens": summary["itens"],
    }
    print(json.dumps(safe_summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
