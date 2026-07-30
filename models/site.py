"""Flags de configuração do site.

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




class SiteFlag(db.Model):
    """Chave-valor booleano para flags de funcionamento do site.

    Exemplos de chaves:
        loja_em_breve          — True = mostra overlay "em breve" na /loja
        plano_saude_em_breve   — True = mostra overlay "em breve" no /plano-saude
    """
    __tablename__ = 'site_flag'

    id    = db.Column(db.Integer, primary_key=True)
    key   = db.Column(db.String(80), unique=True, nullable=False, index=True)
    value = db.Column(db.Boolean, nullable=False, default=False)
    label = db.Column(db.String(120), nullable=True)   # descrição legível para o admin
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    @classmethod
    def get(cls, key: str, default: bool = False) -> bool:
        try:
            row = cls.query.filter_by(key=key).first()
            return row.value if row else default
        except Exception:
            return default

    @classmethod
    def set(cls, key: str, value: bool, label: str | None = None) -> 'SiteFlag':
        row = cls.query.filter_by(key=key).first()
        if row is None:
            row = cls(key=key, value=value, label=label)
            db.session.add(row)
        else:
            row.value = value
            if label is not None:
                row.label = label
        db.session.commit()
        return row



class WaitlistLead(db.Model):
    """Interesse registrado numa funcionalidade ainda não publicada.

    Substitui o beco sem saída do overlay "Em breve": em vez de o visitante
    sair sem deixar rastro, ele informa um contato e vira lista de aviso —
    e, na prática, a primeira lista de clientes de cada linha nova.
    """

    __tablename__ = 'waitlist_lead'
    __table_args__ = (
        db.UniqueConstraint('feature', 'contact', name='uq_waitlist_feature_contact'),
    )

    id = db.Column(db.Integer, primary_key=True)
    #: Chave da funcionalidade ('loja', 'plano_saude').
    feature = db.Column(db.String(60), nullable=False, index=True)
    #: E-mail ou telefone, normalizado em minúsculas e sem espaços nas pontas.
    contact = db.Column(db.String(180), nullable=False)
    city = db.Column(db.String(120), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    notified_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship('User')

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f'<WaitlistLead {self.feature} {self.contact}>'


class ProductEvent(db.Model):
    """Evento persistente e sem conteúdo clínico para medir o funil do produto."""

    __tablename__ = 'product_event'

    id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
    )
    event_name = db.Column(db.String(80), nullable=False, index=True)
    anonymous_id = db.Column(db.String(64), nullable=False, index=True)
    session_id = db.Column(db.String(64), nullable=False, index=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    source_path = db.Column(db.String(300), nullable=True)
    referrer_host = db.Column(db.String(180), nullable=True)
    utm_source = db.Column(db.String(120), nullable=True, index=True)
    utm_medium = db.Column(db.String(120), nullable=True)
    utm_campaign = db.Column(db.String(160), nullable=True)
    properties = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        nullable=False,
        index=True,
    )

    user = db.relationship('User')
