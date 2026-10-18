"""Verificação do token do Heroku (scripts/check_heroku_token.py).

O token expirava em silêncio e o deploy quebrava com um 401 sem explicação.
"""
import io
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))

import check_heroku_token as verificador  # noqa: E402

TOKEN = 'HRKU-token-de-teste'


class _Resposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _api(rotas):
    """Simula a API: ``rotas`` mapeia caminho -> dados JSON ou exceção."""
    def abrir(request, timeout=None):
        caminho = request.full_url.replace(verificador.API_ROOT, '')
        resultado = rotas[caminho]
        if isinstance(resultado, Exception):
            raise resultado
        return _Resposta(json.dumps(resultado).encode('utf-8'))
    return abrir


def _http(codigo):
    return urllib.error.HTTPError('https://api.heroku.com', codigo, 'erro', {}, None)


def test_token_sem_validade_esta_ok():
    abrir = _api({
        '/account': {'email': 'x'},
        '/oauth/authorizations': [{'access_token': {'token': TOKEN, 'expires_in': None}}],
    })
    ok, mensagens = verificador.verificar(TOKEN, abrir=abrir)
    assert ok
    assert 'sem data de expiracao' in mensagens[0]


def test_token_recusado_explica_como_trocar():
    ok, mensagens = verificador.verificar(TOKEN, abrir=_api({'/account': _http(401)}))
    assert not ok
    assert 'HTTP 401' in mensagens[0]
    texto = '\n'.join(mensagens)
    assert 'heroku authorizations:create' in texto
    assert 'Secrets and variables > Actions' in texto
    # Nunca expõe o token nas mensagens.
    assert TOKEN not in texto


def test_token_perto_de_expirar_falha_com_aviso():
    abrir = _api({
        '/account': {},
        '/oauth/authorizations': [
            {'access_token': {'token': 'outro', 'expires_in': None}},
            {'access_token': {'token': TOKEN, 'expires_in': 5 * 86400}},
        ],
    })
    ok, mensagens = verificador.verificar(TOKEN, avisar_dias=15, abrir=abrir)
    assert not ok
    assert 'expira em 5 dia' in mensagens[0]

    # No deploy (--avisar-dias 0) a validade curta não trava a publicação.
    ok, _ = verificador.verificar(TOKEN, avisar_dias=0, abrir=abrir)
    assert ok


def test_api_key_do_dashboard_sem_autorizacao_listada_esta_ok():
    abrir = _api({'/account': {}, '/oauth/authorizations': []})
    ok, _ = verificador.verificar(TOKEN, abrir=abrir)
    assert ok


def test_falha_de_rede_e_token_vazio_nao_levantam_excecao():
    ok, mensagens = verificador.verificar(TOKEN, abrir=_api({'/account': TimeoutError()}))
    assert not ok and 'TimeoutError' in mensagens[0]

    ok, mensagens = verificador.verificar('  ', abrir=_api({}))
    assert not ok and 'vazio' in mensagens[0]


def test_main_usa_variavel_de_ambiente_e_codigo_de_saida(monkeypatch, capsys):
    monkeypatch.setenv('HEROKU_API_KEY', TOKEN)
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setattr(verificador.urllib.request, 'urlopen', _api({'/account': _http(403)}))

    assert verificador.main([]) == 1
    saida = capsys.readouterr()
    assert '::error title=Token do Heroku::' in saida.out
    assert TOKEN not in saida.out + saida.err


def test_deploy_publica_sozinho_no_merge_da_main_com_a_suite():
    """O merge na main publica; a suíte nunca é pulada nesse caminho."""
    raiz = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')
    with open(os.path.join(raiz, 'deploy.yml'), encoding='utf-8') as arquivo:
        deploy = arquivo.read()

    assert 'push:\n    branches: [main]' in deploy
    assert "if: ${{ github.event_name == 'push' || inputs.run_tests }}" in deploy
    assert 'ref: ${{ inputs.ref || github.sha }}' in deploy
    assert 'scripts/check_heroku_token.py' in deploy
    # A trava contra apagar produção continua: nada de push forçado.
    assert not [linha for linha in deploy.splitlines() if 'git push' in linha and '--force' in linha]
    assert 'git merge-base --is-ancestor heroku/main HEAD' in deploy
