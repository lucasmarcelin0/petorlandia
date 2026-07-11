"""Mensagens e notificações (in-app, admin e Web Push).

Extraído de models/base.py na modularização (2026-07-10).
"""
try:
    from extensions import db
except ImportError:
    from .extensions import db

from flask_login import UserMixin
from flask import url_for, request, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta, timezone
import json
from dateutil.relativedelta import relativedelta
from decimal import Decimal, ROUND_CEILING
import unicodedata
import enum
import uuid
from sqlalchemy import Enum, event, func, case, inspect
from enum import Enum
from sqlalchemy import Enum as PgEnum
from sqlalchemy.orm import synonym, object_session, deferred, validates
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.exc import OperationalError, ProgrammingError
from cryptography.fernet import InvalidToken
from functools import lru_cache
try:
    from document_utils import format_cnpj
except ImportError:
    from ..document_utils import format_cnpj
from time_utils import utcnow, now_in_brazil
from security.crypto import (
    MissingMasterKeyError,
    decrypt_text,
    decrypt_text_for_clinic,
    encrypt_text,
    looks_encrypted_text,
)




class Message(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)

    sender_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    receiver_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)

    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    # Relações
    sender = db.relationship('User', foreign_keys=[sender_id], back_populates='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], back_populates='received_messages')
    animal = db.relationship('Animal', backref=db.backref('messages', cascade='all, delete-orphan'))
    clinica = db.relationship('Clinica', backref=db.backref('messages', cascade='all, delete-orphan'))

    lida = db.Column(db.Boolean, default=False)


    def __repr__(self):
        return f'<Message from {self.sender_id} to {self.receiver_id}>'


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    channel = db.Column(db.String(20), nullable=False)
    kind = db.Column(db.String(50), nullable=True)
    sent_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    user = db.relationship('User', backref=db.backref('notifications', cascade='all, delete-orphan'))


class AdminActionNotification(db.Model):
    __tablename__ = 'admin_action_notification'
    __table_args__ = (
        db.UniqueConstraint(
            'recipient_user_id',
            'idempotency_key',
            name='uq_admin_action_notification_recipient_key',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    recipient_user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    event_type = db.Column(db.String(80), nullable=False, index=True)
    entity_type = db.Column(db.String(80), nullable=True, index=True)
    entity_id = db.Column(db.Integer, nullable=True, index=True)
    title = db.Column(db.String(180), nullable=False)
    body = db.Column(db.Text, nullable=True)
    url = db.Column(db.String(500), nullable=True)
    priority = db.Column(db.String(20), nullable=False, default='normal', index=True)
    status = db.Column(db.String(20), nullable=False, default='unread', index=True)
    idempotency_key = db.Column(db.String(180), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    recipient = db.relationship(
        'User',
        foreign_keys=[recipient_user_id],
        backref=db.backref('admin_action_notifications', cascade='all, delete-orphan'),
    )
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id])

    @property
    def is_open(self) -> bool:
        return self.status in {'unread', 'read'}


class PushSubscription(db.Model):
    """Inscrição Web Push (VAPID) de um navegador/dispositivo do usuário."""

    __tablename__ = 'push_subscription'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    # Endpoint é a identidade da inscrição (único por navegador/perfil).
    endpoint = db.Column(db.Text, nullable=False)
    endpoint_hash = db.Column(db.String(64), unique=True, nullable=False)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    last_success_at = db.Column(db.DateTime(timezone=True), nullable=True)
    fail_count = db.Column(db.Integer, nullable=False, default=0)

    user = db.relationship(
        'User',
        backref=db.backref('push_subscriptions', lazy='dynamic', cascade='all, delete-orphan'),
    )

