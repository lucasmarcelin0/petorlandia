"""Mensagens de falha ao enviar solicitações PMO.

O tutor via o texto cru da Google Sheets API ("HttpError 403 ... The caller
does not have permission" + URL da planilha) dentro do formulário.
"""

import os
import sys

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# `app` primeiro: os blueprints importam helpers de lá, e importar o blueprint
# direto deixaria o módulo `app` parcialmente inicializado.
import app as _app  # noqa: F401,E402

from blueprints.vacina_pmo import _mensagem_falha_solicitacao  # noqa: E402


class _FakeHttpError(Exception):
    pass


def test_permissao_negada_vira_mensagem_amigavel():
    exc = _FakeHttpError(
        '<HttpError 403 when requesting '
        'https://sheets.googleapis.com/v4/spreadsheets/1V1uy_x_ZOdZ3KVa3X'
        '?fields=sheets.properties&alt=json returned '
        '"The caller does not have permission".>'
    )
    msg = _mensagem_falha_solicitacao(exc)

    assert 'permissão de acesso' in msg
    # Nada de detalhe interno vazando para o tutor.
    assert 'HttpError' not in msg
    assert 'sheets.googleapis.com' not in msg
    assert '1V1uy_x_ZOdZ3KVa3X' not in msg


def test_planilha_inexistente_tem_mensagem_propria():
    exc = _FakeHttpError('<HttpError 404 ... "Requested entity was not found.">')
    msg = _mensagem_falha_solicitacao(exc)

    assert 'não foi encontrada' in msg
    assert 'HttpError' not in msg


def test_falha_generica_tem_texto_neutro():
    msg = _mensagem_falha_solicitacao(ValueError('conexao caiu no meio'))

    assert 'Tente novamente' in msg
    assert 'conexao caiu no meio' not in msg
