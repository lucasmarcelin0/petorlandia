"""Contrato do url_map: nenhuma rota/endpoint pode sumir durante o refactor.

O snapshot em tests/url_map_snapshot.json foi gerado antes da modularizacao
do app.py. Cada etapa da migracao para blueprints deve manter todos os
endpoints existentes (novos endpoints podem ser adicionados livremente).

Para regenerar o snapshot apos uma mudanca INTENCIONAL de rotas:
    python scripts/gen_url_map_snapshot.py
"""
import json
import pathlib

SNAPSHOT_PATH = pathlib.Path(__file__).parent / "url_map_snapshot.json"


def _current_rules(app):
    """Set de (endpoint, rule, methods) — endpoints podem ter varias rules."""
    rules = set()
    for rule in app.url_map.iter_rules():
        methods = ",".join(
            sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))
        )
        rules.add((rule.endpoint, rule.rule, methods))
    return rules


def test_url_map_matches_snapshot(app):
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    expected = {(e["endpoint"], e["rule"], e["methods"]) for e in snapshot}
    current = _current_rules(app)

    missing = sorted(expected - current)
    assert not missing, (
        f"{len(missing)} rotas sumiram/mudaram no url_map: {missing[:20]}"
    )
