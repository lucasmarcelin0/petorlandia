#!/usr/bin/env python3
"""Confere se o token do Heroku (HEROKU_API_KEY) ainda funciona.

Motivo: o token expirava em silencio (o DEPLOY.md antigo sugeria 30 dias) e so
se descobria na hora de publicar, com um erro 401 sem explicacao no meio do
deploy manual. Este script roda no comeco do workflow Deploy (Heroku): se o
token foi recusado, ou expira em menos de --avisar-dias, falha dizendo
exatamente o que fazer. Serve tambem para conferir o token a mao.

Uso:

    python scripts/check_heroku_token.py              # token em HEROKU_API_KEY
    python scripts/check_heroku_token.py --avisar-dias 15

Nunca imprime o token nem dados da conta.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API_ROOT = "https://api.heroku.com"
ACCEPT = "application/vnd.heroku+json; version=3"

COMO_TROCAR = (
    "Como resolver (uma vez so):\n"
    "  1. Gere um token sem validade: no computador, `heroku authorizations:create "
    "-d \"GitHub Actions\"` (sem -e, nao expira); ou copie a API Key em "
    "dashboard.heroku.com/account (vale ate a senha da conta mudar).\n"
    "  2. Atualize o secret HEROKU_API_KEY em Settings > Secrets and variables > "
    "Actions do repositorio.\n"
    "  3. Se usa o Claude na nuvem, troque tambem a variavel HEROKU_API_KEY do "
    "ambiente."
)


def _get(caminho: str, token: str, abrir=urllib.request.urlopen):
    request = urllib.request.Request(
        f"{API_ROOT}{caminho}",
        headers={"Accept": ACCEPT, "Authorization": f"Bearer {token}"},
    )
    with abrir(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def dias_para_expirar(token: str, abrir=urllib.request.urlopen):
    """Dias até o token expirar; ``None`` se não expira ou não dá para saber.

    O token criado por ``heroku authorizations:create`` aparece na lista de
    autorizações da conta com ``access_token.expires_in`` (segundos, ou nulo
    quando não expira). A API Key do dashboard não aparece ali.
    """
    try:
        autorizacoes = _get("/oauth/authorizations", token, abrir)
    except Exception:  # noqa: BLE001 - validade é informação extra
        return None
    for autorizacao in autorizacoes if isinstance(autorizacoes, list) else []:
        acesso = (autorizacao or {}).get("access_token") or {}
        if acesso.get("token") != token:
            continue
        segundos = acesso.get("expires_in")
        if isinstance(segundos, (int, float)):
            return int(segundos // 86400)
        return None
    return None


def verificar(token: str, avisar_dias: int = 15, abrir=urllib.request.urlopen) -> tuple[bool, list[str]]:
    """``(ok, mensagens)`` sobre o token. Não levanta exceção."""
    token = (token or "").strip()
    if not token:
        return False, ["Falta o token: HEROKU_API_KEY esta vazio.", COMO_TROCAR]

    try:
        _get("/account", token, abrir)
    except urllib.error.HTTPError as erro:
        if erro.code in (401, 403):
            return False, [
                f"O Heroku recusou o token (HTTP {erro.code}): ele expirou ou foi revogado.",
                COMO_TROCAR,
            ]
        return False, [f"O Heroku respondeu HTTP {erro.code} ao conferir o token; tente de novo."]
    except Exception as erro:  # noqa: BLE001 - rede/timeout
        return False, [f"Nao foi possivel falar com o Heroku ({type(erro).__name__}); tente de novo."]

    dias = dias_para_expirar(token, abrir)
    if dias is not None and dias < avisar_dias:
        return False, [
            f"O token do Heroku funciona, mas expira em {dias} dia(s).",
            COMO_TROCAR,
        ]
    validade = "sem data de expiracao conhecida" if dias is None else f"expira em {dias} dias"
    return True, [f"Token do Heroku ok ({validade})."]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--avisar-dias",
        type=int,
        default=15,
        help="falha quando o token expira em menos dias que isso (padrao 15)",
    )
    args = parser.parse_args(argv)

    ok, mensagens = verificar(os.environ.get("HEROKU_API_KEY", ""), args.avisar_dias)
    saida = sys.stdout if ok else sys.stderr
    for mensagem in mensagens:
        print(mensagem, file=saida)
    if not ok and os.environ.get("GITHUB_ACTIONS") == "true":
        # Anotação aparece no topo da execução, sem precisar abrir o log.
        print(f"::error title=Token do Heroku::{mensagens[0]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
