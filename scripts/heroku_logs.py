#!/usr/bin/env python3
"""Imprime as ultimas linhas de log do app no Heroku.

Existe porque quem investiga nem sempre tem o CLI do Heroku a mao -- no
celular nao tem, e num runner de CI tambem nao. Sem isto, um erro que so
aparece em producao vira adivinhacao.

So le: abre uma sessao de log (a API do Heroku devolve uma URL temporaria),
baixa o trecho e escreve na saida padrao.

Uso:

    python scripts/heroku_logs.py --app petorlandia --lines 500
    python scripts/heroku_logs.py --app petorlandia --filtro "animal.*photo"

Token em HEROKU_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

API_ROOT = "https://api.heroku.com"
ACCEPT = "application/vnd.heroku+json; version=3"


def abrir_sessao(app: str, token: str, linhas: int, fonte: str) -> str:
    """Cria a sessao de log e devolve a URL temporaria para baixar."""
    corpo = {"lines": linhas, "tail": False}
    if fonte:
        corpo["source"] = fonte
    request = urllib.request.Request(
        f"{API_ROOT}/apps/{app}/log-sessions",
        data=json.dumps(corpo).encode("utf-8"),
        headers={
            "Accept": ACCEPT,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))["logplex_url"]


def baixar(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, help="Nome do app no Heroku")
    parser.add_argument("--lines", type=int, default=500, help="Quantas linhas trazer")
    parser.add_argument(
        "--source",
        default="app",
        help="'app' (a aplicacao) ou vazio para incluir tambem o roteador",
    )
    parser.add_argument(
        "--filtro",
        default="",
        help="Expressao regular: imprime so as linhas que casarem",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("HEROKU_API_KEY", "")
    if not token:
        print("HEROKU_API_KEY nao definida.", file=sys.stderr)
        return 1

    try:
        url = abrir_sessao(args.app, token, args.lines, args.source)
        texto = baixar(url)
    except Exception as exc:
        print(f"Nao foi possivel ler os logs: {exc}", file=sys.stderr)
        return 1

    if args.filtro:
        padrao = re.compile(args.filtro, re.IGNORECASE)
        linhas = [linha for linha in texto.splitlines() if padrao.search(linha)]
        if not linhas:
            print(f"Nenhuma linha casou com {args.filtro!r} nas ultimas {args.lines}.")
            return 0
        print("\n".join(linhas))
        return 0

    print(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
