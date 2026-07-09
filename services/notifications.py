"""Administrative and partner notifications.

Central point for best-effort email, legacy Notification rows, and actionable
admin alerts shown in the admin notification panel.
"""

from __future__ import annotations

from flask import current_app
from flask_mail import Message as MailMessage

from extensions import db, mail
from time_utils import now_in_brazil


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


def _admin_action_idempotency_key(event_type, entity_type=None, entity_id=None, title=None):
    if entity_type and entity_id:
        return f'{event_type}:{entity_type}:{entity_id}'
    return f'{event_type}:{title or ""}'


def queue_admin_action_notification(
    *,
    title,
    body=None,
    event_type,
    url=None,
    priority='normal',
    entity_type=None,
    entity_id=None,
    idempotency_key=None,
):
    """Add actionable admin alerts to the current DB session without committing."""

    from models import AdminActionNotification

    admins = _admins()
    if not admins:
        return []

    key = idempotency_key or _admin_action_idempotency_key(
        event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        title=title,
    )
    created = []
    for admin in admins:
        exists = AdminActionNotification.query.filter_by(
            recipient_user_id=admin.id,
            idempotency_key=key,
        ).first()
        if exists:
            continue
        note = AdminActionNotification(
            recipient_user_id=admin.id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            body=body,
            url=url,
            priority=priority or 'normal',
            status='unread',
            idempotency_key=key,
            created_at=now_in_brazil(),
        )
        db.session.add(note)
        created.append(note)
    return created


def notify_admin_action(
    *,
    title,
    body=None,
    event_type,
    url=None,
    priority='normal',
    entity_type=None,
    entity_id=None,
    idempotency_key=None,
    email=True,
    commit=True,
):
    """Create actionable admin alerts and optionally email admins."""

    admins = _admins()
    if not admins:
        return []

    if email:
        email_body = body or title
        if url:
            email_body = f'{email_body}\n\nAcesse: {url}'
        _send_email(
            [a.email for a in admins if (a.email or '').strip()],
            f'[PetOrlandia] {title[:80]}',
            email_body,
        )

    try:
        created = queue_admin_action_notification(
            title=title,
            body=body,
            event_type=event_type,
            url=url,
            priority=priority,
            entity_type=entity_type,
            entity_id=entity_id,
            idempotency_key=idempotency_key,
        )
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception('Falha ao preparar AdminActionNotification (%s)', event_type)
        return []
    if commit:
        try:
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()
            current_app.logger.exception('Falha ao registrar AdminActionNotification (%s)', event_type)
            return []
    return created


def _add_notification(user_id, message, *, kind, channel='email'):
    from models import Notification

    try:
        db.session.add(Notification(user_id=user_id, message=message, channel=channel, kind=kind))
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception('Falha ao registrar Notification (%s)', kind)


def notify_admins(texto, *, kind, url=None):
    """Notify admins by email, legacy rows, and actionable admin panel alerts."""

    admins = _admins()
    if not admins:
        return

    body_lines = [texto]
    if url:
        body_lines += ['', f'Acesse: {url}']
    body_lines += ['', 'PetOrlandia (notificacao automatica)']
    body = '\n'.join(body_lines)

    emails = [a.email for a in admins if (a.email or '').strip()]
    _send_email(emails, f'[PetOrlandia] {texto[:80]}', body)
    for admin in admins:
        _add_notification(admin.id, body, kind=kind)
    notify_admin_action(
        title=texto[:180],
        body=body,
        event_type=kind,
        url=url,
        priority='normal',
        idempotency_key=f'legacy:{kind}:{texto[:120]}',
        email=False,
    )


def notify_user(user, subject, body, *, kind):
    """Notify a user by email and record a legacy Notification row."""

    if user is None:
        return
    email = (getattr(user, 'email', '') or '').strip()
    if email and not email.endswith('@convite.petorlandia.local'):
        _send_email([email], subject, body)
    _add_notification(user.id, body, kind=kind)
