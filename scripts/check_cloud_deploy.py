"""Confirma a credencial, o commit em produção e a resposta pública do site."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def heroku(path, token):
    headers = {'Authorization': 'Bearer ' + token,
               'Accept': 'application/vnd.heroku+json; version=3'}
    if path.endswith('/releases'):
        headers['Range'] = 'version ..; order=desc, max=1'
    request = urllib.request.Request(
        'https://api.heroku.com' + path,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def matches(release, slug, expected):
    return (release.get('status') == 'succeeded'
            and bool(slug.get('commit'))
            and (not expected or slug['commit'] == expected))


def check(token, app, expected='', timeout=0, interval=15):
    deadline = time.monotonic() + timeout
    while True:
        releases = heroku(f'/apps/{app}/releases', token)
        release = max(releases, key=lambda item: item['version']) if releases else {}
        slug_id = (release.get('slug') or {}).get('id')
        slug = heroku(f'/apps/{app}/slugs/{slug_id}', token) if slug_id else {}
        if matches(release, slug, expected):
            application = heroku(f'/apps/{app}', token)
            # URL vem do Heroku, não de um PR nem de um parâmetro de entrada.
            request = urllib.request.Request(application['web_url'],
                                             headers={'User-Agent': 'PetOrlandia-deploy-check'})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    if response.status != 200:
                        raise RuntimeError('Site não respondeu HTTP 200.')
                print(f"Produção confirmada: {app}, v{release['version']}, commit {slug['commit']}, site HTTP 200.")
                return 0
            except (urllib.error.URLError, TimeoutError):
                if time.monotonic() >= deadline:
                    raise
                print('Release pronto; aguardando o site responder.', flush=True)
        elif time.monotonic() >= deadline:
            print(f"Publicação não confirmada: release v{release.get('version', '?')}, "
                  f"status {release.get('status', '?')}, commit {slug.get('commit', '?')}; "
                  f"esperado {expected or 'release concluído'}.", file=sys.stderr)
            return 1
        else:
            print('Aguardando a integração GitHub do Heroku publicar o commit aprovado.', flush=True)
        time.sleep(interval)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', default='petorlandia')
    parser.add_argument('--sha', default='')
    parser.add_argument('--timeout', type=int, default=0)
    args = parser.parse_args(argv)
    token = os.environ.get('HEROKU_API_KEY', '')
    if not token:
        print('Falta o secret HEROKU_API_KEY no GitHub Actions.', file=sys.stderr)
        return 1
    try:
        return check(token, args.app, args.sha, args.timeout)
    except urllib.error.HTTPError as error:
        print(f'Consulta recusada (HTTP {error.code}); confira o secret e o acesso ao app.', file=sys.stderr)
    except Exception as error:
        print(f'Não foi possível confirmar a publicação ({type(error).__name__}).', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
