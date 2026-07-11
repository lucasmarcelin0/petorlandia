"""Animais (pets), espécies/raças, documentos e registros de saúde.

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


from .usuarios import _normalize_model_name


class Animal(db.Model):
    __tablename__ = 'animal'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    age = db.Column(db.String(50))
    peso = db.Column(db.Float, nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    sex = db.Column(db.String(10))
    description = db.Column(db.Text)
    status = db.Column(db.String(20))
    image = db.Column(db.String(200))
    photo_rotation = db.Column(db.Integer, default=0)
    photo_zoom = db.Column(db.Float, default=1.0)
    photo_offset_x = db.Column(db.Float, default=0.0)
    photo_offset_y = db.Column(db.Float, default=0.0)
    date_added = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    modo = db.Column(db.String(20), default='doação')
    price = db.Column(db.Float, nullable=True)
    vacinas = db.relationship('Vacina', backref='animal', cascade='all, delete-orphan')

    @property
    def vacinas_ordenadas(self):
        return sorted(self.vacinas, key=lambda v: v.aplicada_em or date.min, reverse=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )

    photos = db.relationship('AnimalPhoto', backref='animal', cascade='all, delete-orphan', lazy=True)
    transactions = db.relationship('Transaction', backref='animal', cascade='all, delete-orphan', lazy=True)
    favorites = db.relationship('Favorite', backref='animal', cascade='all, delete-orphan', lazy=True)

    microchip_number = db.Column(db.String(50), nullable=True)
    neutered = db.Column(db.Boolean, default=False)
    health_plan = db.Column(db.String(100), nullable=True)

    # Carteirinha digital pública: token opaco que habilita /carteirinha/<token>.
    # NULL = carteirinha desativada.
    public_token = db.Column(db.String(32), unique=True, nullable=True)

    removido_em = db.Column(db.DateTime(timezone=True), nullable=True)

    added_by_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
    )
    added_by = db.relationship('User', foreign_keys=[added_by_id])

    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)
    clinica = db.relationship('Clinica', backref='animais')
    casa_de_racao_id = db.Column(db.Integer, db.ForeignKey('casa_de_racao.id', ondelete='SET NULL'), nullable=True)
    casa_de_racao = db.relationship('CasaDeRacao', backref='animais')

    is_alive = db.Column(db.Boolean, default=True)
    falecido_em = db.Column(db.DateTime(timezone=True), nullable=True)

    species_id = db.Column(db.Integer, db.ForeignKey('species.id'))
    breed_id   = db.Column(db.Integer, db.ForeignKey('breed.id'))

    species = db.relationship('Species')
    breed   = db.relationship('Breed')


    blocos_prescricao = db.relationship(
        'BlocoPrescricao',
        back_populates='animal',
        cascade='all, delete-orphan'
    )

    @property
    def age_years(self):
        if self.date_of_birth:
            return relativedelta(date.today(), self.date_of_birth).years
        numero, unidade = _parse_age_value(self.age)
        if numero is None:
            return None
        if unidade == 'meses':
            return 0
        return numero

    @property
    def age_display(self):
        if self.date_of_birth:
            delta = relativedelta(date.today(), self.date_of_birth)
            if delta.years > 0:
                return _format_age_label(delta.years, 'anos')
            return _format_age_label(delta.months, 'meses')
        if self.age:
            numero, unidade = _parse_age_value(self.age)
            if numero is None:
                return self.age
            return _format_age_label(numero, unidade or 'anos')
        return None

    def __str__(self):
        return f"{self.name} ({self.species.name if self.species else self.species})"


class Species(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    def __str__(self):
        return self.name  # 👈 Isso garante que apareça como texto legível no admin


class Breed(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    species_id = db.Column(db.Integer, db.ForeignKey('species.id'), nullable=False)
    species = db.relationship('Species', backref='breeds')

    def __str__(self):
        return self.name



# Transações


class Interest(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    timestamp = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    user = db.relationship(
        'User',
        backref=db.backref('interesses', cascade='all, delete-orphan')
    )
    animal = db.relationship('Animal', backref=db.backref('interesses', cascade='all, delete-orphan'))


class ConsultaToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    tutor_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used = db.Column(db.Boolean, default=False)


class AnimalDocumento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    veterinario_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_url = db.Column(db.String(500), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    uploaded_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    animal = db.relationship('Animal', backref=db.backref('documentos', cascade='all, delete-orphan'))
    veterinario = db.relationship('User')


class AnimalHealthRecord(db.Model):
    """Evento de saude historico que nao pertence ao calendario de vacinas."""
    __tablename__ = 'animal_health_record'

    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id', ondelete='CASCADE'), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    kind = db.Column(db.String(40), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    occurred_on = db.Column(db.Date, nullable=True, index=True)
    next_due_on = db.Column(db.Date, nullable=True, index=True)
    weight_kg = db.Column(db.Float, nullable=True)
    provider_name = db.Column(db.String(160), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)

    animal = db.relationship('Animal', backref=db.backref('health_records', cascade='all, delete-orphan'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])


class CarteirinhaImportacao(db.Model):
    """Auditoria da importacao de uma carteirinha enviada pelo tutor."""
    __tablename__ = 'carteirinha_importacao'

    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id', ondelete='SET NULL'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default='importada')
    dados_extraidos = db.Column(db.Text, nullable=False)
    arquivos_origem = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    confirmed_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=True)

    animal = db.relationship('Animal', backref=db.backref('importacoes_carteirinha', lazy=True))
    user = db.relationship('User', foreign_keys=[user_id])


class TipoRacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marca = db.Column(db.String(100), nullable=False)
    linha = db.Column(db.String(100))  # Ex: "Premium Filhotes", "Golden Fórmula"
    recomendacao = db.Column(db.Float)  # g/kg/dia
    observacoes = db.Column(db.Text)
    peso_pacote_kg = db.Column(db.Float, default=15.0)  # Peso do pacote (kg)
    # Ver Medicamento.species_scope (CG/BE/AMBOS/OUTRO) — usado p/ re-ranquear busca.
    species_scope = db.Column(db.String(20), index=True, nullable=True)
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )


class Racao(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    tipo_racao_id = db.Column(db.Integer, db.ForeignKey('tipo_racao.id'), nullable=False)

    recomendacao_custom = db.Column(db.Float)  # se quiser ajustar a recomendação
    observacoes_racao = db.Column(db.Text)

    data_cadastro = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    animal = db.relationship('Animal', backref=db.backref('racoes', lazy=True, cascade='all, delete-orphan'))
    tipo_racao = db.relationship('TipoRacao', backref=db.backref('usos', lazy=True))

    preco_pago = db.Column(db.Float)  # R$ que o tutor paga
    tamanho_embalagem = db.Column(db.String(50))  # Ex: "15kg", "10,1kg", etc.

    # Veterinário que cadastrou a ração do animal
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
    )



# to implement in the future!


# Avaliações de usuários


class Review(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    reviewed_user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    rating = db.Column(db.Integer, nullable=False)  # 1 a 5
    comment = db.Column(db.Text)
    date = db.Column(db.DateTime(timezone=True), default=now_in_brazil)


# Fotos extras dos animais


class AnimalPhoto(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    image_url = db.Column(db.String(200))
    is_primary = db.Column(db.Boolean, default=False)


# Animais favoritados por usuários


class Favorite(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)

# Loja virtual
# Categorias da Loja — lista fixa controlada usada nos filtros/chips e nos
# formulários de produto. Cada item tem o valor persistido (slug estável), o
# rótulo exibido e um ícone Font Awesome para os chips.


def _normalize_age_unit(value):
    if not value:
        return None
    text = unicodedata.normalize('NFKD', str(value))
    text = text.encode('ASCII', 'ignore').decode('ASCII').strip().lower()
    if text.startswith('mes'):
        return 'meses'
    if text.startswith('ano'):
        return 'anos'
    return text or None


def _parse_age_value(age_text):
    if not age_text:
        return None, None
    parts = str(age_text).split()
    number = None
    try:
        number = int(parts[0])
    except (ValueError, IndexError):
        number = None
    unit = None
    if len(parts) > 1:
        unit = _normalize_age_unit(parts[1])
    return number, unit


def _format_age_label(number, unit):
    if number is None:
        return ''
    normalized = _normalize_age_unit(unit) or 'anos'
    if normalized == 'meses':
        suffix = 'mês' if number == 1 else 'meses'
    else:
        suffix = 'ano' if number == 1 else 'anos'
    return f"{number} {suffix}"


# Partículas de nomes pt-BR que permanecem minúsculas (exceto como 1ª palavra)


@event.listens_for(Animal, "before_insert")
def _normalize_animal_name_before_insert(mapper, connection, target):
    _normalize_model_name(target)


@event.listens_for(Animal, "before_update")
def _normalize_animal_name_before_update(mapper, connection, target):
    _normalize_model_name(target)


# ──────────────────── Serviço de Vacinas Pagas ────────────────────

