#!/usr/bin/env python3
"""Descobre em qual app do Heroku publicar.

Motivo: exigir o nome do app numa variavel deixava o deploy impossivel de
configurar a partir do celular -- o app do GitHub nao abre as configuracoes do
repositorio, e o nome vinha de um `git remote` que so existe no computador.

O token ja diz a quais apps a conta tem acesso. Quando ha um so, nao ha o que
perguntar. Quando ha varios, o nome precisa vir de fora (campo do "Run
workflow" ou variavel), e a mensagem lista as opcoes para escolher.

Uso:

    python scripts/resolve_heroku_app.py            # descobre pela conta
    python scripts/resolve_heroku_app.py --name app # confere o que foi pedido

Imprime o nome do app na saida padrao. Token em HEROKU_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

API_ROOT = "https://api.heroku.com"
ACCEPT = "application/vnd.heroku+json; version=3"


class AppIndefinido(ValueError):
    """Nao da para decidir sozinho em qual app publicar."""


def listar_apps(token: str) -> list[str]:
    request = urllib.request.Request(
        f"{API_ROOT}/apps",
        headers={"Accept": ACCEPT, "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        dados = json.loads(response.read().decode("utf-8"))
    return [app["name"] for app in dados if app.get("name")]


def resolve_app(pedido: str, disponiveis: list[str]) -> str:
    """Nome do app a publicar, ou ``AppIndefinido`` com o que fazer a seguir."""
    pedido = (pedido or "").strip()
    if pedido:
        # Nome digitado no disparo: so confere que a conta enxerga esse app,
        # para o erro aparecer aqui e nao num `git push` recusado adiante.
        if disponiveis and pedido not in disponiveis:
            raise AppIndefinido(
                f"A conta deste token nao tem o app '{pedido}'. "
                f"Disponiveis: {', '.join(sorted(disponiveis)) or 'nenhum'}."
            )
        return pedido

    if not disponiveis:
        raise AppIndefinido(
            "O token nao enxerga nenhum app do Heroku. Confira se ele e da "
            "conta certa e se nao expirou."
        )
    if len(disponiveis) > 1:
        raise AppIndefinido(
            "A conta tem mais de um app; diga qual publicar no campo 'app' do "
            f"Run workflow (ou na variavel HEROKU_APP_NAME). Opcoes: "
            f"{', '.join(sorted(disponiveis))}."
        )
    return disponiveis[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="", help="Nome do app, quando ja se sabe")
    args = parser.parse_args(argv)

    token = os.environ.get("HEROKU_API_KEY", "")
    if not token:
        print("HEROKU_API_KEY nao definida.", file=sys.stderr)
        return 1

    try:
        disponiveis = listar_apps(token)
    except Exception as exc:
        print(f"Nao foi possivel consultar os apps do Heroku: {exc}", file=sys.stderr)
        return 1

    try:
        print(resolve_app(args.name, disponiveis))
    except AppIndefinido as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
