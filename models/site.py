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

