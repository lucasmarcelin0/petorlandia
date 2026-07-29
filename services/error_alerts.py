"""Alerta por e-mail quando uma página quebra com erro 500.

Sem isso, um 500 vira só uma linha de log que ninguém lê — a página fica no ar
quebrada até um cliente reclamar. É exatamente o que aconteceria com /servicos,
que recebe o tráfego vindo da prefeitura.

Duas travas para o alerta não virar spam:

* o mesmo (rota + tipo de exceção) só alerta uma vez a cada
  ``ERROR_ALERT_COOLDOWN_MINUTES``;
* nada aqui toca o banco. A sessão do SQLAlchemy costuma estar suja quando o
  handler roda, e gravar nela transformaria o alerta em um segundo erro.
"""

from __future__ import annotations

import time
import traceback

from flask import current_app

#: Último envio por chave (rota + exceção), em epoch seconds.
_last_sent: dict[str, float] = {}
_MAX_KEYS = 500


def _cooldown_seconds() -> int:
    minutes = current_app.config.get('ERROR_ALERT_COOLDOWN_MINUTES', 30)
    try:
        return max(int(minutes), 1) * 60
    except (TypeError, ValueError):
        return 30 * 60


def _recipients() -> list[str]:
    """Para quem mandar. Config explícita ganha; senão, os admins do banco."""

    configured = current_app.config.get('ERROR_ALERT_EMAILS')
    if configured:
        if isinstance(configured, str):
            return [e.strip() for e in configured.split(',') if e.strip()]
        return list(configured)

    try:
        from services.notifications import _admins

        return [a.email for a in _admins() if (a.email or '').strip()]
    except Exception:  # noqa: BLE001
        return []


def _should_send(key: str) -> bool:
    now = time.time()
    last = _last_sent.get(key)
    if last is not None and (now - last) < _cooldown_seconds():
        return False

    if len(_last_sent) > _MAX_KEYS:
        _last_sent.clear()
    _last_sent[key] = now
    return True


def reset() -> None:
    """Zera a janela de silêncio. Usado em testes."""

    _last_sent.clear()


def alert_unhandled_error(error, *, path: str, request_id: str | None, method: str = 'GET') -> bool:
    """Envia o alerta. Devolve True se um e-mail saiu de fato.

    Nunca levanta: um problema no alerta não pode substituir a página de erro
    que o usuário precisa ver.
    """

    try:
        if not current_app.config.get('ERROR_ALERTS_ENABLED', True):
            return False

        exc_name = type(error).__name__
        key = f'{path}|{exc_name}'
        if not _should_send(key):
            return False

        recipients = _recipients()
        if not recipients:
            return False

        detalhe = ''.join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )[-3000:]

        from services.notifications import _send_email

        return _send_email(
            recipients,
            f'[PetOrlandia] Erro 500 em {path}',
            (
                f'Uma página quebrou para um visitante.\n\n'
                f'Rota: {method} {path}\n'
                f'Exceção: {exc_name}: {error}\n'
                f'Request ID: {request_id or "-"}\n\n'
                f'Próximos erros iguais nesta rota ficam silenciados por '
                f'{_cooldown_seconds() // 60} minutos.\n\n'
                f'--- traceback ---\n{detalhe}'
            ),
        )
    except Exception:  # noqa: BLE001
        current_app.logger.warning('Falha ao enviar alerta de erro 500', exc_info=True)
        return False
