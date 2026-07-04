"""Notificações administrativas e de parceiros.

Central único para avisar admins de eventos acionáveis (novos cadastros
pendentes, candidaturas) e avisar parceiros do desfecho da análise.
Todos os envios são best-effort: falha de e-mail nunca quebra o fluxo.
"""

from __future__ import annotations

from flask import current_app
from flask_mail import Message as MailMessage

from extensions import db, mail


def _admins():
    from models import User

    return User.query.filter(db.func.lower(User.role) == 'admin').all()


def _send_email(recipients, subject, body):
    if not recipients:
        return False
    if not current_app.config.get('MAIL_DEFAULT_SENDER'):
        return False
    try:
        mail.send(MailMessage(subject=subject, recipients=recipients, body=body))
        return True
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning('Falha ao enviar e-mail "%s": %s', subject, exc)
        return False


def _add_notification(user_id, message, *, kind, channel='email'):
    from models import Notification

    try:
        db.session.add(Notification(user_id=user_id, message=message, channel=channel, kind=kind))
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception('Falha ao registrar Notification (%s)', kind)


def notify_admins(texto, *, kind, url=None):
    """Avisa todos os admins por e-mail e registra Notification para cada um."""

    admins = _admins()
    if not admins:
        return

    body_lines = [texto]
    if url:
        body_lines += ['', f'Acesse: {url}']
    body_lines += ['', '— PetOrlândia (notificação automática)']
    body = '\n'.join(body_lines)

    emails = [a.email for a in admins if (a.email or '').strip()]
    _send_email(emails, f'[PetOrlândia] {texto[:80]}', body)
    for admin in admins:
        _add_notification(admin.id, body, kind=kind)


def notify_user(user, subject, body, *, kind):
    """Avisa um usuário (parceiro/candidato) por e-mail e registra Notification."""

    if user is None:
        return
    email = (getattr(user, 'email', '') or '').strip()
    if email and not email.endswith('@convite.petorlandia.local'):
        _send_email([email], subject, body)
    _add_notification(user.id, body, kind=kind)
