"""Regenera tests/url_map_snapshot.json a partir do app atual.

Rodar apenas quando uma mudanca de rotas for intencional:
    python scripts/gen_url_map_snapshot.py
"""
import json
import os
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

from app_factory import create_app  # noqa: E402


def main():
    app = create_app()
    rules = sorted(
        (
            r.endpoint,
            r.rule,
            ",".join(sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS"))),
        )
        for r in app.url_map.iter_rules()
    )
    out = PROJECT_ROOT / "tests" / "url_map_snapshot.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(
            [{"endpoint": e, "rule": r, "methods": m} for e, r, m in rules],
            f,
            indent=1,
            ensure_ascii=False,
        )
    print(f"{len(rules)} rules -> {out}")


if __name__ == "__main__":
    main()
