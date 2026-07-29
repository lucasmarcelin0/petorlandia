"""Alerta de erro 500: dispara uma vez, silencia repetição e nunca quebra a página."""

import os

import pytest

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

from app_factory import create_app  # noqa: E402
from extensions import db  # noqa: E402
from services import error_alerts  # noqa: E402


@pytest.fixture
def app():
    """create_app() devolve sempre o mesmo singleton, que na suíte completa já
    atendeu requests de outros arquivos — por isso não registramos rota nova
    aqui. Os testes chamam o handler direto dentro de um request context."""
    application = create_app()
    anterior = {
        key: application.config.get(key)
        for key in ('TESTING', 'PROPAGATE_EXCEPTIONS', 'WTF_CSRF_ENABLED',
                    'ERROR_ALERTS_ENABLED', 'ERROR_ALERT_EMAILS',
                    'ERROR_ALERT_COOLDOWN_MINUTES')
    }
    application.config.update(
        TESTING=False,          # precisamos do handler real de exceção
        PROPAGATE_EXCEPTIONS=False,
        WTF_CSRF_ENABLED=False,
        ERROR_ALERTS_ENABLED=True,
        ERROR_ALERT_EMAILS='dono@example.com',
        ERROR_ALERT_COOLDOWN_MINUTES=30,
    )

    with application.app_context():
        db.create_all()
        error_alerts.reset()
        yield application
        db.session.remove()

    application.config.update(anterior)


@pytest.fixture
def enviados(monkeypatch):
    capturados = []
    monkeypatch.setattr(
        'services.notifications._send_email',
        lambda recipients, subject, body: capturados.append((recipients, subject)) or True,
    )
    return capturados


def test_handler_de_500_dispara_alerta_e_devolve_a_pagina(app, enviados):
    from request_hooks import handle_unhandled_exception

    with app.test_request_context('/servicos'):
        _, status = handle_unhandled_exception(RuntimeError('falha simulada'))

    assert status == 500
    assert len(enviados) == 1
    recipients, subject = enviados[0]
    assert recipients == ['dono@example.com']
    assert '/servicos' in subject


def test_erro_repetido_nao_reenvia_dentro_da_janela(app, enviados):
    from request_hooks import handle_unhandled_exception

    for _ in range(5):
        with app.test_request_context('/servicos'):
            handle_unhandled_exception(RuntimeError('falha simulada'))

    assert len(enviados) == 1, 'a mesma falha nao pode gerar uma enxurrada de e-mails'


def test_rotas_diferentes_alertam_separadamente(app, enviados):
    from request_hooks import handle_unhandled_exception

    for path in ('/servicos', '/loja', '/precos'):
        with app.test_request_context(path):
            handle_unhandled_exception(RuntimeError('falha simulada'))

    assert len(enviados) == 3


def test_alerta_desligado_nao_envia(app, enviados):
    from request_hooks import handle_unhandled_exception

    app.config['ERROR_ALERTS_ENABLED'] = False

    with app.test_request_context('/servicos'):
        _, status = handle_unhandled_exception(RuntimeError('falha simulada'))

    assert status == 500
    assert enviados == []


def test_falha_no_alerta_nao_esconde_a_pagina_de_erro(app, monkeypatch):
    """Se o e-mail explodir, o visitante ainda tem que receber a página 500."""
    def explode(*args, **kwargs):
        raise RuntimeError('SMTP fora do ar')

    monkeypatch.setattr('services.notifications._send_email', explode)

    from request_hooks import handle_unhandled_exception

    with app.test_request_context('/servicos'):
        _, status = handle_unhandled_exception(RuntimeError('falha simulada'))

    assert status == 500
