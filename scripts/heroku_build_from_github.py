#!/usr/bin/env python3
"""Publica um commit no Heroku pelo mesmo caminho da integracao GitHub.

Motivo: a integracao GitHub do Heroku publica por *build de tarball*, sem
passar pelo Git do Heroku. Depois do primeiro deploy por ela, o `main` do
`git.heroku.com` fica parado no ultimo `git push` manual e deixa de dizer o
que esta no ar. Em 06/11/2026 ele estava num push avulso de 31/10 que nunca
entrou na `main`, e o fallback por `git push` sem `--force` se recusava a
publicar, justo quando a integracao tinha parado de disparar.

Este script:

1. le o commit do slug em producao (a verdade sobre o que esta no ar);
2. recusa publicar se esse commit nao for ancestral do ref -- a mesma trava
   do push sem --force, agora contra producao de fato;
3. cria um build a partir de ``https://github.com/<repo>/archive/<sha>.tar.gz``
   e espera ele terminar.

O release phase (`flask db upgrade`) roda depois; quem espera por ele e
`scripts/wait_heroku_release.py`.

Uso:

    python scripts/heroku_build_from_github.py --app petorlandia --repo dono/repo --sha <sha>

Sai com 0 quando o build passou ou quando producao ja esta no commit, e grava
``publicou=true|false`` em ``$GITHUB_OUTPUT`` quando existe. O token vem de
HEROKU_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API_ROOT = "https://api.heroku.com"
ACCEPT = "application/vnd.heroku+json; version=3"


def _request(path: str, token: str, data: dict | None = None, extra_headers: dict | None = None):
    headers = {"Accept": ACCEPT, "Authorization": f"Bearer {token}"}
    headers.update(extra_headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(API_ROOT + path, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def production_commit(app: str, token: str) -> str | None:
    """Commit do slug do release mais recente que concluiu."""
    releases = _request(
        f"/apps/{app}/releases", token, extra_headers={"Range": "version ..; order=desc, max=20"}
    )
    for release in releases:
        if release.get("status") != "succeeded":
            continue
        slug_id = (release.get("slug") or {}).get("id")
        if not slug_id:
            continue
        return _request(f"/apps/{app}/slugs/{slug_id}", token).get("commit") or None
    return None


def is_ancestor(ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
    )
    return result.returncode == 0


def decide(current: str | None, sha: str, ancestor=is_ancestor) -> str:
    """'publicar', 'nada' (producao ja esta nele) ou 'recusar'."""
    if not current:
        return "publicar"
    if current == sha:
        return "nada"
    if not ancestor(current, sha):
        return "recusar"
    return "publicar"


def create_build(app: str, token: str, repo: str, sha: str) -> dict:
    source = {"url": f"https://github.com/{repo}/archive/{sha}.tar.gz", "version": sha}
    return _request(f"/apps/{app}/builds", token, data={"source_blob": source})


def wait_build(app: str, token: str, build_id: str, timeout: int, interval: int = 10) -> dict:
    deadline = time.monotonic() + timeout
    build: dict = {}
    while time.monotonic() < deadline:
        try:
            build = _request(f"/apps/{app}/builds/{build_id}", token)
        except urllib.error.HTTPError:
            raise
        except Exception as exc:
            # Falha de rede pontual nao derruba o deploy: tenta de novo.
            print(f"aviso: {exc}", file=sys.stderr)
        else:
            if build.get("status") in ("succeeded", "failed"):
                return build
        time.sleep(interval)
    return build


def build_log(build: dict) -> str:
    url = build.get("output_stream_url")
    if not url:
        return ""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - depende do Heroku
        return f"(nao foi possivel ler o log do build: {exc})"


def _output(publicou: bool) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"publicou={'true' if publicou else 'false'}\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True)
    parser.add_argument("--repo", required=True, help="dono/repositorio no GitHub (publico)")
    parser.add_argument("--sha", required=True, help="commit completo a publicar")
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args(argv)

    token = os.environ.get("HEROKU_API_KEY", "").strip()
    if not token:
        print("Falta HEROKU_API_KEY.", file=sys.stderr)
        return 1

    current = production_commit(args.app, token)
    print(f"Em producao: {current or 'nenhum commit registrado'}")
    decisao = decide(current, args.sha)
    if decisao == "nada":
        print("Producao ja esta neste commit; nada a publicar.")
        _output(False)
        return 0
    if decisao == "recusar":
        print(
            f"Producao ({current}) tem commit que {args.sha} nao tem. "
            "Traga producao para o ref antes de publicar (DEPLOY.md).",
            file=sys.stderr,
        )
        return 1

    build = create_build(args.app, token, args.repo, args.sha)
    print(f"Build {build.get('id')} criado para {args.sha}.")
    build = wait_build(args.app, token, build["id"], args.timeout)
    status = build.get("status")
    if status != "succeeded":
        print(f"Build terminou como {status or 'sem resposta'}.", file=sys.stderr)
        log = build_log(build)
        if log:
            print("--- final do log do build ---", file=sys.stderr)
            print(log[-6000:], file=sys.stderr)
        return 1
    print("Build concluido.")
    _output(True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
