"""Planos de saúde pet: planos, assinaturas, coberturas e sinistros.

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




class HealthPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    clinica_id = db.Column(
        db.Integer,
        db.ForeignKey('clinica.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    clinica = db.relationship('Clinica', backref=db.backref('health_plans', lazy='dynamic'))
    coverages = db.relationship(
        'HealthCoverage',
        back_populates='plan',
        cascade='all, delete-orphan',
        lazy='selectin',
    )

    def __repr__(self):
        return f"{self.name} (R$ {self.price})"


class HealthSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('health_plan.id'), nullable=False)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'))

    active = db.Column(db.Boolean, default=False)
    start_date = db.Column(db.DateTime(timezone=True), default=utcnow)
    end_date = db.Column(db.DateTime(timezone=True), nullable=True)
    guardian_document = db.Column(db.String(40), nullable=True)
    animal_document = db.Column(db.String(60), nullable=True)
    contract_reference = db.Column(db.String(80), nullable=True)
    consent_signed_at = db.Column(db.DateTime, nullable=True)
    consent_ip = db.Column(db.String(64), nullable=True)

    animal = db.relationship('Animal', backref=db.backref('health_subscriptions', cascade='all, delete-orphan'))
    plan = db.relationship('HealthPlan', backref='subscriptions')
    user = db.relationship(
        'User',
        backref=db.backref('health_subscriptions', cascade='all, delete-orphan')
    )
    payment = db.relationship('Payment', backref='subscriptions')
    coverage_usages = db.relationship(
        'HealthCoverageUsage',
        back_populates='subscription',
        cascade='all, delete-orphan',
    )
    claims = db.relationship(
        'HealthClaim',
        back_populates='subscription',
        cascade='all, delete-orphan',
    )

    def __repr__(self):
        return f"{self.animal.name} – {self.plan.name}"


class HealthCoverage(db.Model):
    __tablename__ = 'health_coverage'

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('health_plan.id'), nullable=False)
    procedure_code = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    coverage_type = db.Column(db.String(40), default='procedimento')
    monetary_limit = db.Column(db.Numeric(12, 2), nullable=True)
    limit_period = db.Column(db.String(20), default='lifetime')
    waiting_period_days = db.Column(db.Integer, default=0)
    deductible_amount = db.Column(db.Numeric(12, 2), default=0)
    requires_authorization = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text, nullable=True)

    plan = db.relationship('HealthPlan', back_populates='coverages')

    def matches(self, candidate):
        text = (candidate or '').strip().lower()
        return bool(text and text == (self.procedure_code or '').strip().lower())


class HealthPlanOnboarding(db.Model):
    __tablename__ = 'health_plan_onboarding'

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('health_plan.id'), nullable=False)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    guardian_document = db.Column(db.String(40), nullable=False)
    animal_document = db.Column(db.String(60), nullable=True)
    contract_reference = db.Column(db.String(80), nullable=True)
    extra_notes = db.Column(db.Text, nullable=True)
    consent_signed_at = db.Column(db.DateTime, default=utcnow)
    consent_ip = db.Column(db.String(64), nullable=True)
    attachments = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(20), default='pending_payment')
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    plan = db.relationship('HealthPlan', backref=db.backref('onboarding_records', cascade='all, delete-orphan'))
    animal = db.relationship('Animal', backref=db.backref('plan_onboardings', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('plan_onboardings', cascade='all, delete-orphan'))


class HealthCoverageUsage(db.Model):
    __tablename__ = 'health_coverage_usage'
    __table_args__ = (
        db.UniqueConstraint('subscription_id', 'coverage_id', 'orcamento_item_id', name='uq_subscription_coverage_item'),
    )

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('health_subscription.id'), nullable=False)
    coverage_id = db.Column(db.Integer, db.ForeignKey('health_coverage.id'), nullable=False)
    consulta_id = db.Column(db.Integer, db.ForeignKey('consulta.id'), nullable=True)
    orcamento_item_id = db.Column(
        db.Integer,
        db.ForeignKey('orcamento_item.id', ondelete='CASCADE'),
        nullable=True,
    )
    amount_billed = db.Column(db.Numeric(12, 2), default=0)
    amount_covered = db.Column(db.Numeric(12, 2), default=0)
    status = db.Column(db.String(20), default='pending')
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    subscription = db.relationship('HealthSubscription', back_populates='coverage_usages')
    coverage = db.relationship('HealthCoverage', backref=db.backref('usages', cascade='all, delete-orphan'))
    consulta = db.relationship('Consulta', backref=db.backref('coverage_usages', cascade='all, delete-orphan'))
    orcamento_item = db.relationship('OrcamentoItem', backref=db.backref('usage_record', uselist=False, cascade='all, delete-orphan'))


class HealthClaim(db.Model):
    __tablename__ = 'health_claim'

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('health_subscription.id'), nullable=True)
    consulta_id = db.Column(db.Integer, db.ForeignKey('consulta.id'), nullable=True)
    coverage_id = db.Column(db.Integer, db.ForeignKey('health_coverage.id'), nullable=True)
    insurer_reference = db.Column(db.String(80), nullable=True)
    request_format = db.Column(db.String(20), default='json')
    payload = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(20), default='received')
    response_payload = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    subscription = db.relationship('HealthSubscription', back_populates='claims')
    coverage = db.relationship('HealthCoverage', backref=db.backref('claims', cascade='all, delete-orphan'))
    consulta = db.relationship('Consulta', backref=db.backref('claims', cascade='all, delete-orphan'))


# ---------------------------------------------------------------------------
# Planos de Banho e Tosa
# ---------------------------------------------------------------------------

