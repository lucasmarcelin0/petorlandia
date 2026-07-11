"""Programas municipais (PMO): vacinação, castração e serviço pago de vacinas.

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




class PmoVaccinationVisit(db.Model):
    __tablename__ = 'pmo_vaccination_visit'
    __table_args__ = (
        db.UniqueConstraint(
            'spreadsheet_id',
            'sheet_gid',
            'source_row',
            name='uq_pmo_vaccination_visit_sheet_row',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    spreadsheet_id = db.Column(db.String(128), nullable=False, index=True)
    sheet_gid = db.Column(db.String(64), nullable=False, index=True)
    sheet_title = db.Column(db.String(120), nullable=False, index=True)
    source_row = db.Column(db.Integer, nullable=False)
    tutor_name = db.Column(db.String(255), nullable=False)
    address = db.Column(db.String(500), nullable=True)
    phone1 = db.Column(db.String(32), nullable=True)
    phone2 = db.Column(db.String(32), nullable=True)
    dogs = db.Column(db.Integer, nullable=False, default=0)
    cats = db.Column(db.Integer, nullable=False, default=0)
    requested_date = db.Column(db.Date, nullable=True)
    vaccine_date = db.Column(db.Date, nullable=True)
    shift = db.Column(db.String(30), nullable=True)
    note = db.Column(db.Text, nullable=True)
    password = db.Column(db.String(32), nullable=False)
    certificate_url = db.Column(db.String(500), nullable=True)
    public_token = db.Column(db.String(96), unique=True, nullable=True, index=True)
    attended_by = db.Column(db.String(255), nullable=True)
    # Doses perdidas nesta casa (frasco quebrado, refluxo etc.); perdas do
    # turno no "Controle de doses" = soma das visitas do turno.
    losses = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    tutor_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    evaluation_rating = db.Column(db.Integer, nullable=True)
    evaluation_registration_rating = db.Column(db.Integer, nullable=True)
    evaluation_service_rating = db.Column(db.Integer, nullable=True)
    evaluation_information_rating = db.Column(db.Integer, nullable=True)
    evaluation_survey_rating = db.Column(db.Integer, nullable=True)
    evaluation_comment = db.Column(db.Text, nullable=True)
    evaluated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    geocode_lat = db.Column(db.Float, nullable=True)
    geocode_lng = db.Column(db.Float, nullable=True)
    geocode_address_key = db.Column(db.String(500), nullable=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    tutor_user = db.relationship('User', foreign_keys=[tutor_user_id])
    animals = db.relationship(
        'PmoVaccinationAnimal',
        backref='visit',
        cascade='all, delete-orphan',
        order_by='PmoVaccinationAnimal.position',
    )


class PmoVaccinationAnimal(db.Model):
    __tablename__ = 'pmo_vaccination_animal'

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(
        db.Integer,
        db.ForeignKey('pmo_vaccination_visit.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    position = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    species = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='pendente')
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id', ondelete='SET NULL'), nullable=True, index=True)
    vaccine_id = db.Column(db.Integer, db.ForeignKey('vacina.id', ondelete='SET NULL'), nullable=True, index=True)
    vaccinated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    animal = db.relationship('Animal', foreign_keys=[animal_id])
    vaccine = db.relationship('Vacina', foreign_keys=[vaccine_id])


class PmoCastrationRequest(db.Model):
    __tablename__ = 'pmo_castration_request'
    __table_args__ = (
        db.UniqueConstraint(
            'spreadsheet_id',
            'sheet_gid',
            'source_row',
            name='uq_pmo_castration_request_sheet_row',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    spreadsheet_id = db.Column(db.String(128), nullable=False, index=True)
    sheet_gid = db.Column(db.String(64), nullable=False, index=True)
    sheet_title = db.Column(db.String(120), nullable=False, index=True)
    source_row = db.Column(db.Integer, nullable=False)
    tutor_name = db.Column(db.String(255), nullable=False)
    cpf = db.Column(db.String(32), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    address = db.Column(db.String(500), nullable=True)
    phone1 = db.Column(db.String(32), nullable=True)
    phone2 = db.Column(db.String(32), nullable=True)
    dogs = db.Column(db.Integer, nullable=False, default=0)
    cats = db.Column(db.Integer, nullable=False, default=0)
    preferred_contact = db.Column(db.String(80), nullable=True)
    female_status = db.Column(db.String(120), nullable=True)
    health_notes = db.Column(db.Text, nullable=True)
    note = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), nullable=False, default='solicitado', index=True)
    public_token = db.Column(db.String(96), unique=True, nullable=True, index=True)
    tutor_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    submitted_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    synced_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    tutor_user = db.relationship('User', foreign_keys=[tutor_user_id])
    animals = db.relationship(
        'PmoCastrationAnimal',
        backref='request',
        cascade='all, delete-orphan',
        order_by='PmoCastrationAnimal.position',
    )


class PmoCastrationAnimal(db.Model):
    __tablename__ = 'pmo_castration_animal'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(
        db.Integer,
        db.ForeignKey('pmo_castration_request.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    position = db.Column(db.Integer, nullable=False)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id', ondelete='SET NULL'), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    species = db.Column(db.String(20), nullable=False)
    sex = db.Column(db.String(20), nullable=True)
    age_label = db.Column(db.String(80), nullable=True)
    weight_kg = db.Column(db.Float, nullable=True)
    already_neutered = db.Column(db.Boolean, nullable=True)
    status = db.Column(db.String(30), nullable=False, default='solicitado')
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    animal = db.relationship('Animal', foreign_keys=[animal_id])


class PmoRouteOptimizationBackup(db.Model):
    __tablename__ = 'pmo_route_optimization_backup'

    id = db.Column(db.Integer, primary_key=True)
    spreadsheet_id = db.Column(db.String(128), nullable=False, index=True)
    sheet_gid = db.Column(db.String(64), nullable=False, index=True)
    sheet_title = db.Column(db.String(120), nullable=False, index=True)
    shift = db.Column(db.String(30), nullable=False, index=True)
    source_rows_json = db.Column(db.Text, nullable=False)
    before_values_json = db.Column(db.Text, nullable=False)
    after_values_json = db.Column(db.Text, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    undone_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    created_by = db.relationship('User', foreign_keys=[created_by_id])


class VaccineServiceItem(db.Model):
    """Item do catálogo de vacinas pagas (preço único da plataforma)."""

    __tablename__ = 'vaccine_service_item'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    fabricante = db.Column(db.String(120), nullable=True)
    descricao = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(255), nullable=True)
    especies = db.Column(db.String(40), nullable=False, default='cao,gato')  # csv: cao,gato
    preco = db.Column(db.Numeric(10, 2), nullable=False)
    valor_repasse = db.Column(db.Numeric(10, 2), nullable=True)
    provider_vet_id = db.Column(
        db.Integer,
        db.ForeignKey('veterinario.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    doses_info = db.Column(db.String(200), nullable=True)  # ex.: "Dose única anual"
    cidade = db.Column(db.String(100), nullable=True, index=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    provider_vet = db.relationship('Veterinario', foreign_keys=[provider_vet_id])

    def especies_list(self):
        return [e.strip() for e in (self.especies or '').split(',') if e.strip()]


class VaccineServiceRequest(db.Model):
    """Pedido de vacina paga: solicitação → pagamento → vet → aplicação."""

    __tablename__ = 'vaccine_service_request'

    STATUS_LABELS = {
        'pendente_pagamento': 'Aguardando pagamento',
        'pago': 'Pago — aguardando veterinário',
        'atribuido': 'Veterinário designado',
        'agendado': 'Agendado',
        'concluido': 'Vacina aplicada',
        'cancelado': 'Cancelado',
        'reembolsado': 'Reembolsado',
    }

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id', ondelete='CASCADE'), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey('vaccine_service_item.id'), nullable=False)

    # Snapshot do item no momento da compra (preço pode mudar depois)
    item_nome = db.Column(db.String(120), nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    fabricante = db.Column(db.String(120), nullable=True)
    valor_repasse = db.Column(db.Numeric(10, 2), nullable=True)

    address_street = db.Column(db.String(200), nullable=True)
    address_number = db.Column(db.String(20), nullable=True)
    address_complement = db.Column(db.String(100), nullable=True)
    address_neighborhood = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(32), nullable=True)
    preferred_date = db.Column(db.Date, nullable=True)
    preferred_shift = db.Column(db.String(20), nullable=True)  # Manha/Tarde
    note = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(30), nullable=False, default='pendente_pagamento', index=True)
    public_token = db.Column(db.String(96), unique=True, nullable=False, index=True)

    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id', ondelete='SET NULL'), nullable=True)
    assigned_vet_id = db.Column(db.Integer, db.ForeignKey('veterinario.id', ondelete='SET NULL'), nullable=True, index=True)
    scheduled_date = db.Column(db.Date, nullable=True)
    scheduled_shift = db.Column(db.String(20), nullable=True)
    vaccinated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    vacina_id = db.Column(db.Integer, db.ForeignKey('vacina.id', ondelete='SET NULL'), nullable=True)

    cancel_reason = db.Column(db.String(255), nullable=True)
    refund_status = db.Column(db.String(30), nullable=True)  # solicitado/concluido/falhou

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    user = db.relationship('User', foreign_keys=[user_id])
    animal = db.relationship('Animal', foreign_keys=[animal_id])
    item = db.relationship('VaccineServiceItem', foreign_keys=[item_id])
    payment = db.relationship('Payment', foreign_keys=[payment_id])
    assigned_vet = db.relationship('Veterinario', foreign_keys=[assigned_vet_id])
    vacina = db.relationship('Vacina', foreign_keys=[vacina_id])
    events = db.relationship(
        'VaccineServiceEvent',
        backref='request',
        cascade='all, delete-orphan',
        order_by='VaccineServiceEvent.created_at',
    )
    request_items = db.relationship(
        'VaccineServiceRequestItem',
        back_populates='request',
        cascade='all, delete-orphan',
        order_by='VaccineServiceRequestItem.id',
    )

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def address_full(self):
        parts = [self.address_street or '']
        if self.address_number:
            parts[0] += f', {self.address_number}'
        if self.address_complement:
            parts.append(self.address_complement)
        if self.address_neighborhood:
            parts.append(self.address_neighborhood)
        return ' — '.join(p for p in parts if p)


class VaccineServiceRequestItem(db.Model):
    """Snapshot de cada vacina incluída em um pedido pago."""

    __tablename__ = 'vaccine_service_request_item'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(
        db.Integer,
        db.ForeignKey('vaccine_service_request.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    item_id = db.Column(
        db.Integer,
        db.ForeignKey('vaccine_service_item.id', ondelete='SET NULL'),
        nullable=True,
    )
    nome = db.Column(db.String(120), nullable=False)
    fabricante = db.Column(db.String(120), nullable=True)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    valor_repasse = db.Column(db.Numeric(10, 2), nullable=True)
    vacina_id = db.Column(
        db.Integer,
        db.ForeignKey('vacina.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    request = db.relationship('VaccineServiceRequest', back_populates='request_items')
    item = db.relationship('VaccineServiceItem', foreign_keys=[item_id])
    vacina = db.relationship('Vacina', foreign_keys=[vacina_id])


class VaccineServiceEvent(db.Model):
    """Histórico/auditoria de cada pedido (linha do tempo do usuário)."""

    __tablename__ = 'vaccine_service_event'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(
        db.Integer,
        db.ForeignKey('vaccine_service_request.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    event = db.Column(db.String(40), nullable=False)  # criado/pago/atribuido/agendado/...
    note = db.Column(db.Text, nullable=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    actor = db.relationship('User', foreign_keys=[actor_user_id])


# ─────────────────────────────────────────────────────────
#  SiteFlag — feature flags on/off controlados pelo admin
# ─────────────────────────────────────────────────────────

