#!/usr/bin/env python3
"""Espera o release do Heroku terminar e diz se ele passou.

Motivo: `git push heroku` volta assim que o build termina, mas o
`release: flask db upgrade` do Procfile roda *depois*. Sem esperar por ele, um
deploy com migration quebrada aparece como sucesso no CI enquanto o dyno novo
se recusa a subir -- exatamente o erro que o DEPLOY.md descreve.

Uso:

    python scripts/wait_heroku_release.py --app minha-app --after-version 412

Sai com 0 quando o release mais novo passou, 1 quando falhou ou estourou o
tempo. O token vem de HEROKU_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_ROOT = "https://api.heroku.com"
ACCEPT = "application/vnd.heroku+json; version=3"
TERMINAL_STATUSES = {"succeeded", "failed"}


def _request(url: str, token: str, extra_headers: dict | None = None):
    headers = {"Accept": ACCEPT, "Authorization": f"Bearer {token}"}
    headers.update(extra_headers or {})
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def latest_release(app: str, token: str) -> dict | None:
    """Release mais recente do app, ou ``None`` quando o app nunca publicou."""
    releases = _request(
        f"{API_ROOT}/apps/{app}/releases",
        token,
        {"Range": "version ..; order=desc, max=1"},
    )
    return releases[0] if releases else None


def release_log(release: dict, token: str) -> str:
    """Log do release phase, quando o Heroku ainda o disponibiliza."""
    url = release.get("output_stream_url")
    if not url:
        return ""
    try:
        request = urllib.request.Request(url)
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - depende do Heroku
        return f"(nao foi possivel ler o log do release: {exc})"


def is_new_release(release: dict | None, after_version: int) -> bool:
    """O release ja e o que este deploy criou (e nao o anterior)?"""
    if not release:
        return False
    return int(release.get("version") or 0) > after_version


def wait_for_release(app: str, token: str, after_version: int, timeout: int, interval: int = 5) -> int:
    deadline = time.monotonic() + timeout
    seen = None
    while time.monotonic() < deadline:
        try:
            release = latest_release(app, token)
        except urllib.error.HTTPError as exc:
            print(f"Heroku respondeu {exc.code} ao consultar releases.", file=sys.stderr)
            return 1
        except Exception as exc:
            # Falha de rede pontual nao derruba o deploy: tenta de novo.
            print(f"aviso: {exc}", file=sys.stderr)
            time.sleep(interval)
            continue

        if is_new_release(release, after_version):
            seen = release
            status = (release.get("status") or "").lower()
            if status in TERMINAL_STATUSES:
                versao = release.get("version")
                descricao = (release.get("description") or "").strip()
                if status == "succeeded":
                    print(f"Release v{versao} concluido: {descricao}")
                    return 0
                print(f"Release v{versao} FALHOU: {descricao}", file=sys.stderr)
                log = release_log(release, token)
                if log:
                    print("--- log do release phase ---", file=sys.stderr)
                    print(log, file=sys.stderr)
                return 1
        time.sleep(interval)

    if seen is None:
        print(
            f"Nenhum release novo apareceu em {timeout}s (ultimo continua v{after_version}).",
            file=sys.stderr,
        )
    else:
        print(
            f"Release v{seen.get('version')} continuou pendente por {timeout}s.",
            file=sys.stderr,
        )
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, help="Nome do app no Heroku")
    parser.add_argument(
        "--after-version",
        type=int,
        default=0,
        help="Versao do release anterior ao push (espera por uma maior)",
    )
    parser.add_argument("--timeout", type=int, default=900, help="Tempo maximo de espera, em segundos")
    parser.add_argument("--interval", type=int, default=5, help="Intervalo entre consultas, em segundos")
    args = parser.parse_args(argv)

    token = os.environ.get("HEROKU_API_KEY", "")
    if not token:
        print("HEROKU_API_KEY nao definida.", file=sys.stderr)
        return 1

    return wait_for_release(args.app, token, args.after_version, args.timeout, args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
