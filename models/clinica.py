"""Clínicas: cadastro, equipe, estoque, convites e configurações.

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




@lru_cache(maxsize=1)
def _clinica_columns() -> set[str]:
    try:
        inspector = inspect(db.engine)
        return {column["name"] for column in inspector.get_columns("clinica")}
    except Exception:  # noqa: BLE001 - falhar silenciosamente para ambientes sem migration
        return set()


def clinica_has_column(column_name: str) -> bool:
    return column_name in _clinica_columns()


def get_clinica_field(clinica, column_name: str, default=None):
    if not clinica or not clinica_has_column(column_name):
        return default
    try:
        value = getattr(clinica, column_name)
    except (OperationalError, ProgrammingError):
        session = object_session(clinica)
        if session:
            session.rollback()
        _clinica_columns.cache_clear()
        return default
    return value if value is not None else default


def _encrypt_nfse_value(value):
    if value is None:
        return None
    if isinstance(value, str) and value == "":
        return None
    if isinstance(value, str) and looks_encrypted_text(value):
        return value
    return encrypt_text(value)


def _decrypt_nfse_value(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if not looks_encrypted_text(value):
        return value
    try:
        return decrypt_text(value)
    except (InvalidToken, MissingMasterKeyError):
        return value


class Clinica(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    # pendente = aguardando aprovação do admin; ativa = aprovada; rejeitada/suspensa
    status = db.Column(db.String(20), nullable=False, default='ativa', server_default='ativa', index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=True)
    cnpj = db.Column(db.String(18))
    endereco = db.Column(db.String(200))
    telefone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    logotipo = db.Column(db.String(200))  # caminho para imagem do logo
    modo_entrega = db.Column(db.String(20), default='plataforma', nullable=False)
    valor_frete = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    pedido_minimo_entrega = db.Column(db.Numeric(10, 2), nullable=True)
    prazo_entrega_min = db.Column(db.Integer, nullable=True)
    prazo_entrega_max = db.Column(db.Integer, nullable=True)
    photo_rotation = db.Column(db.Integer, default=0)
    photo_zoom = db.Column(db.Float, default=1.0)
    photo_offset_x = db.Column(db.Float, default=0.0)
    photo_offset_y = db.Column(db.Float, default=0.0)
    inscricao_municipal = deferred(db.Column(db.String(40)))
    inscricao_estadual = deferred(db.Column(db.String(40)))
    regime_tributario = deferred(db.Column(db.String(60)))
    cnae = deferred(db.Column(db.String(20)))
    codigo_servico = deferred(db.Column(db.String(30)))
    aliquota_iss = deferred(db.Column(db.Numeric(5, 2)))
    aliquota_pis = deferred(db.Column(db.Numeric(5, 2)))
    aliquota_cofins = deferred(db.Column(db.Numeric(5, 2)))
    aliquota_csll = deferred(db.Column(db.Numeric(5, 2)))
    aliquota_ir = deferred(db.Column(db.Numeric(5, 2)))
    municipio_nfse = deferred(db.Column(db.String(60)))
    _nfse_username = deferred(db.Column("nfse_username", db.String(120)))
    _nfse_password = deferred(db.Column("nfse_password", db.String(120)))
    _nfse_cert_path = deferred(db.Column("nfse_cert_path", db.String(200)))
    _nfse_cert_password = deferred(db.Column("nfse_cert_password", db.String(120)))
    _nfse_token = deferred(db.Column("nfse_token", db.String(200)))
    fiscal_ready = deferred(db.Column(db.Boolean, default=False))

    _nfse_encrypted_fields = {
        "nfse_username": "_nfse_username",
        "nfse_password": "_nfse_password",
        "nfse_cert_path": "_nfse_cert_path",
        "nfse_cert_password": "_nfse_cert_password",
        "nfse_token": "_nfse_token",
    }

    @validates("cnpj")
    def _normalize_cnpj(self, key, value):
        formatted = format_cnpj(value)
        return formatted or None

    @property
    def fiscal_ready_status(self) -> bool:
        return bool(get_clinica_field(self, "fiscal_ready", False))

    def get_nfse_encrypted(self, field_name: str):
        attr_name = self._nfse_encrypted_fields.get(field_name, field_name)
        return getattr(self, attr_name)

    def _get_nfse_username(self):
        return _decrypt_nfse_value(self._nfse_username)

    def _set_nfse_username(self, value):
        self._nfse_username = _encrypt_nfse_value(value)

    nfse_username = synonym("_nfse_username", descriptor=property(_get_nfse_username, _set_nfse_username))

    def _get_nfse_password(self):
        return _decrypt_nfse_value(self._nfse_password)

    def _set_nfse_password(self, value):
        self._nfse_password = _encrypt_nfse_value(value)

    nfse_password = synonym("_nfse_password", descriptor=property(_get_nfse_password, _set_nfse_password))

    def _get_nfse_cert_path(self):
        return _decrypt_nfse_value(self._nfse_cert_path)

    def _set_nfse_cert_path(self, value):
        self._nfse_cert_path = _encrypt_nfse_value(value)

    nfse_cert_path = synonym("_nfse_cert_path", descriptor=property(_get_nfse_cert_path, _set_nfse_cert_path))

    def _get_nfse_cert_password(self):
        return _decrypt_nfse_value(self._nfse_cert_password)

    def _set_nfse_cert_password(self, value):
        self._nfse_cert_password = _encrypt_nfse_value(value)

    nfse_cert_password = synonym(
        "_nfse_cert_password",
        descriptor=property(_get_nfse_cert_password, _set_nfse_cert_password),
    )

    def _get_nfse_token(self):
        return _decrypt_nfse_value(self._nfse_token)

    def _set_nfse_token(self, value):
        self._nfse_token = _encrypt_nfse_value(value)

    nfse_token = synonym("_nfse_token", descriptor=property(_get_nfse_token, _set_nfse_token))

    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    owner = db.relationship('User', backref=db.backref('clinicas', foreign_keys='Clinica.owner_id'), foreign_keys=[owner_id])

    registered_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    registered_by = db.relationship('User', foreign_keys=[registered_by_id])

    veterinarios = db.relationship('Veterinario', backref='clinica', lazy=True)
    veterinarios_associados = db.relationship(
        'Veterinario',
        secondary='veterinario_clinica',
        back_populates='clinicas',
    )
    eventos = db.relationship(
        'AgendaEvento',
        back_populates='clinica',
        cascade='all, delete-orphan',
        lazy=True,
    )


    @property
    def logo_url(self):
        """Return an absolute URL for the clinic logo.

        Handles three cases:
        * ``http``/``https`` URLs stored directly in ``logotipo``.
        * Paths starting with ``/`` which are joined with ``request.url_root``.
        * Bare filenames stored in the uploads folder.
        """
        if not self.logotipo:
            return ""
        if self.logotipo.startswith("http"):
            return self.logotipo
        if self.logotipo.startswith("/"):
            return request.url_root.rstrip("/") + self.logotipo
        return url_for(
            "static", filename=f"uploads/clinicas/{self.logotipo}", _external=True
        )


    def __str__(self):
        return f'{self.nome} ({self.cnpj})'


class ClinicHours(db.Model):
    __tablename__ = 'clinic_hours'
    id = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    dia_semana = db.Column(db.String(20), nullable=False)
    hora_abertura = db.Column(db.Time, nullable=False)
    hora_fechamento = db.Column(db.Time, nullable=False)

    clinica = db.relationship(
        'Clinica',
        backref=db.backref('horarios', cascade='all, delete-orphan'),
    )


class PartnerInvite(db.Model):
    """Convite enviado pelo admin para qualquer tipo de parceiro/usuário.

    O link tokenizado leva a uma página única de onboarding que cria a conta
    e o estabelecimento (quando aplicável) já aprovados.
    """

    __tablename__ = 'partner_invite'

    TIPOS = {
        'clinica': 'Clínica veterinária',
        'casa_de_racao': 'Casa de ração',
        'petshop': 'Petshop',
        'banho_tosa': 'Banho e tosa',
        'veterinario': 'Veterinário(a)',
        'petsitter': 'Petsitter',
        'usuario': 'Usuário / tutor',
    }

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(30), nullable=False, index=True)
    nome = db.Column(db.String(150), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    telefone = db.Column(db.String(20), nullable=True)
    cidade = db.Column(db.String(120), nullable=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    used_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    used_by = db.relationship('User', foreign_keys=[used_by_id])

    @property
    def tipo_label(self):
        return self.TIPOS.get(self.tipo, self.tipo)

    @property
    def is_expired(self):
        expires_at = self.expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return bool(expires_at and expires_at < datetime.now(timezone.utc))


class ClinicStaff(db.Model):
    __tablename__ = 'clinic_staff'
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    can_manage_clients = db.Column(db.Boolean, default=False)
    can_manage_animals = db.Column(db.Boolean, default=False)
    can_manage_staff = db.Column(db.Boolean, default=False)
    can_manage_schedule = db.Column(db.Boolean, default=False)
    can_manage_inventory = db.Column(db.Boolean, default=False)
    can_view_full_calendar = db.Column(db.Boolean, default=True, nullable=False)

    clinic = db.relationship(
        'Clinica',
        backref=db.backref('staff_members', cascade='all, delete-orphan'),
    )
    user = db.relationship(
        'User',
        backref=db.backref('clinic_roles', cascade='all, delete-orphan'),
        passive_deletes=True,
    )


class VetClinicInvite(db.Model):
    __tablename__ = 'vet_clinic_invite'
    id = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    veterinario_id = db.Column(db.Integer, db.ForeignKey('veterinario.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    clinica = db.relationship('Clinica', backref='vet_invites')
    veterinario = db.relationship('Veterinario', backref='clinic_invites')

# Itens de estoque específicos por clínica


class ExternalOnboardingInvite(db.Model):
    __tablename__ = 'external_onboarding_invite'

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    invite_type = db.Column(db.String(20), nullable=False, index=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=True)
    exame_id = db.Column(db.Integer, db.ForeignKey('exame_solicitado.id'), nullable=True)
    exame_imagem_id = db.Column(db.Integer, db.ForeignKey('exame_imagem.id'), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    referrer_vet_id = db.Column(db.Integer, db.ForeignKey('veterinario.id'), nullable=True)
    message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)

    clinica = db.relationship('Clinica', foreign_keys=[clinica_id])
    tutor = db.relationship('User', foreign_keys=[tutor_id])
    animal = db.relationship('Animal', foreign_keys=[animal_id])
    exame = db.relationship('ExameSolicitado', foreign_keys=[exame_id])
    exame_imagem = db.relationship('ExameImagem', foreign_keys=[exame_imagem_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    referrer_vet = db.relationship('Veterinario', foreign_keys=[referrer_vet_id])


class ClinicInventoryItem(db.Model):
    __tablename__ = 'clinic_inventory_item'
    id = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    categoria = db.Column(db.String(120), nullable=True)
    quantity = db.Column(db.Integer, default=0)
    unit = db.Column(db.String(50))
    min_quantity = db.Column(db.Integer, nullable=True)
    max_quantity = db.Column(db.Integer, nullable=True)

    clinica = db.relationship('Clinica', backref='inventory_items')
    movements = db.relationship(
        'ClinicInventoryMovement',
        back_populates='item',
        cascade='all, delete-orphan',
    )

    nome = synonym('name')
    quantidade = synonym('quantity')
    unidade = synonym('unit')


ClinicInventory = ClinicInventoryItem


class ClinicInventoryMovement(db.Model):
    __tablename__ = 'clinic_inventory_movement'

    id = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)
    item_id = db.Column(db.Integer, db.ForeignKey('clinic_inventory_item.id', ondelete='CASCADE'), nullable=False)
    quantity_change = db.Column(db.Integer, nullable=True, default=0)
    quantity_before = db.Column(db.Integer, nullable=True, default=0)
    quantity_after = db.Column(db.Integer, nullable=True, default=0)
    tipo = db.Column(db.String(20), nullable=True)
    motivo = db.Column(db.String(200), nullable=True)
    responsavel_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    clinica = db.relationship('Clinica', backref='inventory_movements')
    item = db.relationship('ClinicInventoryItem', back_populates='movements')

    inventory_id = synonym('item_id')
    quantidade = synonym('quantity_change')


class ClinicTaxes(db.Model):
    __tablename__ = 'clinic_taxes'
    __table_args__ = (
        db.UniqueConstraint('clinic_id', 'month', name='uq_clinic_taxes_clinic_month'),
    )

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    month = db.Column(db.Date, nullable=False, index=True)
    iss_total = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    das_total = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    retencoes_pj = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    fator_r = db.Column(db.Numeric(6, 4), nullable=False, default=Decimal('0.0000'))
    faixa_simples = db.Column(db.Integer, nullable=True)
    projecao_anual = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, onupdate=now_in_brazil, nullable=False)

    clinic = db.relationship(
        'Clinica',
        backref=db.backref('tax_reports', cascade='all, delete-orphan', lazy=True),
    )


class ClinicNotification(db.Model):
    __tablename__ = 'clinic_notifications'

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=True)
    type = db.Column(db.String(20), nullable=False, default='info')
    month = db.Column(db.Date, nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil)
    resolved = db.Column(db.Boolean, nullable=False, default=False)
    resolution_date = db.Column(db.DateTime(timezone=True), nullable=True)

    clinic = db.relationship(
        'Clinica',
        backref=db.backref('clinic_notifications', cascade='all, delete-orphan', lazy=True),
    )

