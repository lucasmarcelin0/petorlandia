"""Casas de ração parceiras, grooming e assinaturas de ração.

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




class CasaDeRacao(db.Model):
    __tablename__ = 'casa_de_racao'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    # Subtipo do estabelecimento de varejo: 'casa_de_racao' | 'petshop' | 'banho_tosa'.
    # Usado apenas para rotulagem/capacidades (ver services/establishments.py);
    # o modelo e os fluxos de loja são compartilhados entre os subtipos.
    tipo = db.Column(db.String(20), default='casa_de_racao', nullable=False)
    razao_social = db.Column(db.String(200), nullable=True)
    cnpj = db.Column(db.String(18), nullable=True, unique=True)
    descricao = db.Column(db.Text, nullable=True)
    telefone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    endereco = db.Column(db.String(200), nullable=True)
    logotipo = db.Column(db.String(200), nullable=True)
    photo_rotation = db.Column(db.Integer, default=0)
    photo_zoom = db.Column(db.Float, default=1.0)
    photo_offset_x = db.Column(db.Float, default=0.0)
    photo_offset_y = db.Column(db.Float, default=0.0)
    # 'pendente' = aguardando aprovação do admin, 'ativa' = aprovada, 'suspensa' = bloqueada
    status = db.Column(db.String(20), default='pendente', nullable=False)
    # 'plataforma' = entregadores da rede, 'propria' = vendedor gerencia a entrega
    modo_entrega = db.Column(db.String(20), default='plataforma', nullable=False)
    valor_frete = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    pedido_minimo_entrega = db.Column(db.Numeric(10, 2), nullable=True)
    prazo_entrega_min = db.Column(db.Integer, nullable=True)
    prazo_entrega_max = db.Column(db.Integer, nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    registered_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    owner = db.relationship(
        'User',
        backref=db.backref('casas_de_racao', foreign_keys='CasaDeRacao.owner_id'),
        foreign_keys=[owner_id],
    )
    registered_by = db.relationship('User', foreign_keys=[registered_by_id])

    @validates('cnpj')
    def _normalize_cnpj(self, key, value):
        formatted = format_cnpj(value)
        return formatted or None

    @property
    def logo_url(self):
        if not self.logotipo:
            return ''
        if self.logotipo.startswith('http'):
            return self.logotipo
        if self.logotipo.startswith('/'):
            return request.url_root.rstrip('/') + self.logotipo
        return url_for('static', filename=f'uploads/casas_de_racao/{self.logotipo}', _external=True)

    def __str__(self):
        return f'{self.nome} ({self.cnpj or "sem CNPJ"})'


class CasaDeRacaoOnboardingInvite(db.Model):
    __tablename__ = 'casa_de_racao_onboarding_invite'

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(
        db.Integer,
        db.ForeignKey('casa_de_racao.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)

    casa_de_racao = db.relationship(
        'CasaDeRacao',
        backref=db.backref('onboarding_invites', cascade='all, delete-orphan'),
    )

    @property
    def is_expired(self):
        expires_at = self.expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return bool(expires_at and expires_at < datetime.now(timezone.utc))


class CasaDeRacaoHorario(db.Model):
    __tablename__ = 'casa_de_racao_horario'

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(db.Integer, db.ForeignKey('casa_de_racao.id'), nullable=False)
    dia_semana = db.Column(db.String(20), nullable=False)
    hora_abertura = db.Column(db.Time, nullable=False)
    hora_fechamento = db.Column(db.Time, nullable=False)

    casa_de_racao = db.relationship(
        'CasaDeRacao',
        backref=db.backref('horarios', cascade='all, delete-orphan'),
    )


class StorePaymentAccount(db.Model):
    __tablename__ = 'store_payment_account'
    __table_args__ = (
        db.UniqueConstraint('casa_de_racao_id', 'provider', name='uq_store_payment_provider'),
        db.UniqueConstraint('clinica_id', 'provider', name='uq_store_payment_clinic_provider'),
    )

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(
        db.Integer,
        db.ForeignKey('casa_de_racao.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    clinica_id = db.Column(
        db.Integer,
        db.ForeignKey('clinica.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    provider = db.Column(db.String(40), nullable=False, default='mercado_pago')
    provider_user_id = db.Column(db.String(80), nullable=True, index=True)
    public_key = db.Column(db.String(255), nullable=True)
    access_token_encrypted = db.Column(db.Text, nullable=True)
    refresh_token_encrypted = db.Column(db.Text, nullable=True)
    oauth_state = db.Column(db.String(128), nullable=True, unique=True, index=True)
    code_verifier_encrypted = db.Column(db.Text, nullable=True)
    token_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    error_message = db.Column(db.Text, nullable=True)
    connected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_refreshed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=now_in_brazil,
        onupdate=now_in_brazil,
    )

    casa_de_racao = db.relationship(
        'CasaDeRacao',
        backref=db.backref('payment_accounts', cascade='all, delete-orphan', lazy='dynamic'),
    )
    clinica = db.relationship(
        'Clinica',
        backref=db.backref('payment_accounts', cascade='all, delete-orphan', lazy='dynamic'),
    )

    @property
    def is_connected(self):
        return self.status == 'connected' and bool(self.access_token_encrypted)

    @property
    def access_token(self):
        return decrypt_text(self.access_token_encrypted) if self.access_token_encrypted else None

    @access_token.setter
    def access_token(self, value):
        self.access_token_encrypted = encrypt_text(value) if value else None

    @property
    def refresh_token(self):
        return decrypt_text(self.refresh_token_encrypted) if self.refresh_token_encrypted else None

    @refresh_token.setter
    def refresh_token(self, value):
        self.refresh_token_encrypted = encrypt_text(value) if value else None

    @property
    def code_verifier(self):
        return decrypt_text(self.code_verifier_encrypted) if self.code_verifier_encrypted else None

    @code_verifier.setter
    def code_verifier(self, value):
        self.code_verifier_encrypted = encrypt_text(value) if value else None


GROOMING_SERVICE_LABELS = {
    'banho': 'Banho',
    'tosa': 'Tosa',
    'banho_e_tosa': 'Banho e Tosa',
}


class GroomingPlan(db.Model):
    __tablename__ = 'grooming_plan'

    id = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(
        db.Integer,
        db.ForeignKey('clinica.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    casa_de_racao_id = db.Column(
        db.Integer,
        db.ForeignKey('casa_de_racao.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    # 'banho' | 'tosa' | 'banho_e_tosa'
    service_type = db.Column(db.String(30), nullable=False, default='banho_e_tosa')
    price = db.Column(db.Numeric(10, 2), nullable=False)
    sessions_per_month = db.Column(db.Integer, nullable=False, default=1)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    clinica = db.relationship('Clinica', backref=db.backref('grooming_plans', lazy='dynamic'))
    casa_de_racao = db.relationship('CasaDeRacao', backref=db.backref('grooming_plans', lazy='dynamic'))
    subscriptions = db.relationship(
        'GroomingSubscription',
        back_populates='plan',
        cascade='all, delete-orphan',
        lazy='dynamic',
    )

    @property
    def service_label(self):
        return GROOMING_SERVICE_LABELS.get(self.service_type, self.service_type)

    @property
    def active_subscriptions_count(self):
        return self.subscriptions.filter_by(active=True).count()

    @property
    def provider_name(self):
        if self.clinica:
            return self.clinica.nome
        if self.casa_de_racao:
            return self.casa_de_racao.nome
        return 'PetOrlandia'

    def __repr__(self):
        return f"{self.name} — {self.service_label} (R$ {self.price})"


class GroomingSubscription(db.Model):
    __tablename__ = 'grooming_subscription'

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(
        db.Integer,
        db.ForeignKey('grooming_plan.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    animal_id = db.Column(
        db.Integer,
        db.ForeignKey('animal.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    active = db.Column(db.Boolean, nullable=False, default=False)
    start_date = db.Column(db.DateTime(timezone=True), nullable=True)
    # ID do preapproval no Mercado Pago para cancelamento futuro
    mp_preapproval_id = db.Column(db.String(128), nullable=True)
    sessions_used_this_month = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    plan = db.relationship('GroomingPlan', back_populates='subscriptions')
    animal = db.relationship('Animal', backref=db.backref('grooming_subscriptions', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('grooming_subscriptions', lazy='dynamic'))


class RacaoAssinatura(db.Model):
    """Assinatura recorrente de produto da loja (ração etc.) via preapproval MP.

    Segue o mesmo desenho da GroomingSubscription: o preapproval é criado na
    conta da plataforma; o repasse ao lojista segue o fluxo manual existente.
    A cada pagamento recorrente aprovado (webhook), um ciclo é registrado e a
    casa de ração é notificada para preparar a entrega.
    """

    __tablename__ = 'racao_assinatura'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey('product.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    variant_id = db.Column(
        db.Integer,
        db.ForeignKey('product_variant.id', ondelete='SET NULL'),
        nullable=True,
    )
    animal_id = db.Column(
        db.Integer,
        db.ForeignKey('animal.id', ondelete='SET NULL'),
        nullable=True,
    )
    quantidade = db.Column(db.Integer, nullable=False, default=1)
    # Frequência em dias (15, 30, 60...) — convertida para o preapproval do MP.
    frequencia_dias = db.Column(db.Integer, nullable=False, default=30)
    # Preço público do ciclo, congelado na adesão.
    preco_ciclo = db.Column(db.Numeric(10, 2), nullable=False)
    # pending (aguardando 1º pagamento) | active | cancelled
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    mp_preapproval_id = db.Column(db.String(128), nullable=True)
    ciclos_pagos = db.Column(db.Integer, nullable=False, default=0)
    ultimo_ciclo_em = db.Column(db.DateTime(timezone=True), nullable=True)
    endereco_entrega = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    activated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    cancelled_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship('User', backref=db.backref('racao_assinaturas', lazy='dynamic'))
    product = db.relationship('Product', backref=db.backref('assinaturas', lazy='dynamic'))
    variant = db.relationship('ProductVariant')
    animal = db.relationship('Animal')

    @property
    def frequencia_label(self):
        mapping = {15: 'Quinzenal', 30: 'Mensal', 60: 'A cada 2 meses', 90: 'A cada 3 meses'}
        return mapping.get(self.frequencia_dias, f'A cada {self.frequencia_dias} dias')






















#testing sandbox

