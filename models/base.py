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
from decimal import Decimal
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


class Endereco(db.Model):
    __tablename__ = 'endereco'
    id = db.Column(db.Integer, primary_key=True)
    cep = db.Column(db.String(9), nullable=True)  # Ex: 14620-000
    rua = db.Column(db.String(120), nullable=True)
    numero = db.Column(db.String(20), nullable=True)
    complemento = db.Column(db.String(100), nullable=True)
    bairro = db.Column(db.String(100), nullable=True)
    cidade = db.Column(db.String(100), nullable=True)
    estado = db.Column(db.String(2), nullable=True)  # Ex: SP
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    def __repr__(self):
        return f"{self.rua}, {self.numero or 's/n'} - {self.bairro}, {self.cidade}/{self.estado} - {self.cep}"

    # relação 1‑para‑1 de volta
    pickup_location = db.relationship(
        "PickupLocation",
        back_populates="endereco",
        uselist=False
    )

    @property
    def full(self):
        """Rua, número, bairro – cidade/UF – CEP."""
        partes = []
        if self.rua:
            partes.append(f"{self.rua}{', ' + self.numero if self.numero else ''}")
        if self.bairro:
            partes.append(self.bairro)
        if self.cidade and self.estado:
            partes.append(f"{self.cidade}/{self.estado}")
        if self.cep:
            partes.append(f"CEP {self.cep}")
        return " – ".join(partes)


class UserRole(enum.Enum):
    tutor = 'tutor'
    adotante = 'adotante'
    doador = 'doador'
    veterinario = 'veterinario'
    admin = 'admin'
    vacinador = 'vacinador'
    parceiro = 'parceiro'


# Usuário
class User(UserMixin, db.Model):
    __table_args__ = {'extend_existing': True}  # <- isso permite redefinir sem erro

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default='adotante', nullable=True)



    phone = db.Column(db.String(20))
    phone2 = db.Column(db.String(20), nullable=True)

    address = db.Column(db.String(200))
    endereco_id = db.Column(db.Integer, db.ForeignKey('endereco.id'), nullable=True)
    endereco = db.relationship('Endereco', backref='usuarios')



    profile_photo = db.Column(db.String(200))
    photo_rotation = db.Column(db.Integer, default=0)
    photo_zoom = db.Column(db.Float, default=1.0)
    photo_offset_x = db.Column(db.Float, default=0.0)
    photo_offset_y = db.Column(db.Float, default=0.0)

    # 🆕 Novos campos adicionados:
    cpf = db.Column(db.String(14), unique=True, nullable=True)  # Ex: 123.456.789-00
    rg = db.Column(db.String(20), nullable=True)               # Ex: 12.345.678-9
    date_of_birth = db.Column(db.Date, nullable=True)          # Armazenado como data
    worker = db.Column(db.String(50), nullable=True)
    # dentro da classe User
    veterinario = db.relationship(
        'Veterinario',
        back_populates='user',
        uselist=False,
        cascade='all, delete-orphan',
    )




    animals = db.relationship(
        'Animal',
        backref='owner',
        cascade="all, delete",
        lazy=True,
        foreign_keys='Animal.user_id'  # 🛠 THIS LINE
    )




    # Correção dos campos:
    # lazy='select' (default) on purpose -- these used to be lazy='selectin',
    # which taxed EVERY User load site-wide with 2 extra Message queries even
    # though the collections are only read in delete_account() (rare) and the
    # mensagens.html inbox template (which eager-loads sent_messages itself
    # via the Message.sender selectinload option in _get_inbox_messages()).
    sent_messages = db.relationship(
        'Message',
        foreign_keys='Message.sender_id',
        back_populates='sender',
        cascade='all, delete-orphan',
    )
    received_messages = db.relationship(
        'Message',
        foreign_keys='Message.receiver_id',
        back_populates='receiver',
        cascade='all, delete-orphan',
    )

    given_reviews = db.relationship(
        'Review',
        foreign_keys='Review.reviewer_id',
        backref=db.backref('reviewer'),
        cascade='all, delete-orphan',
        lazy=True,
    )
    received_reviews = db.relationship(
        'Review',
        foreign_keys='Review.reviewed_user_id',
        backref=db.backref('reviewed'),
        cascade='all, delete-orphan',
        lazy=True,
    )
    favorites = db.relationship('Favorite', backref=db.backref('user'), cascade='all, delete-orphan', lazy=True)

    eventos_responsavel = db.relationship(
        'AgendaEvento',
        back_populates='responsavel',
        foreign_keys='AgendaEvento.responsavel_id',
        cascade='all, delete-orphan',
        lazy=True,
    )
    eventos_colaborador = db.relationship(
        'AgendaEvento',
        secondary='evento_colaboradores',
        back_populates='colaboradores',
        lazy=True,
    )

    added_by_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
    )  # 🆕
    added_by = db.relationship('User', remote_side=[id], backref='users_added')  # 🆕



    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)
    clinica = db.relationship('Clinica', backref='usuarios', foreign_keys=[clinica_id])
    casa_de_racao_id = db.Column(db.Integer, db.ForeignKey('casa_de_racao.id', ondelete='SET NULL'), nullable=True)
    casa_de_racao = db.relationship('CasaDeRacao', backref='tutores', foreign_keys=[casa_de_racao_id])
    is_private = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)




    @property
    def added_by_display(self):
        return self.added_by.name if self.added_by else "N/A"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __str__(self):
        return f'{self.name} ({self.email})'









class DataSharePartyType(enum.Enum):
    clinic = 'clinic'
    veterinarian = 'veterinarian'
    insurer = 'insurer'


class DataShareAccess(db.Model):
    __tablename__ = 'data_share_access'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=True)
    source_clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)

    granted_to_type = db.Column(PgEnum(DataSharePartyType, name='data_share_party_type'), nullable=False)
    granted_to_id = db.Column(db.Integer, nullable=False)
    granted_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    granted_via = db.Column(db.String(50), nullable=True)
    grant_reason = db.Column(db.String(255), nullable=True)

    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revoked_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    revoke_reason = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('data_share_accesses', cascade='all, delete-orphan'))
    animal = db.relationship('Animal', foreign_keys=[animal_id], backref=db.backref('data_share_accesses', cascade='all, delete-orphan'))
    source_clinic = db.relationship('Clinica', foreign_keys=[source_clinic_id])
    granted_by_user = db.relationship('User', foreign_keys=[granted_by])
    revoked_by_user = db.relationship('User', foreign_keys=[revoked_by])

    @property
    def is_active(self):
        if self.revoked_at is not None:
            return False
        if self.expires_at and self.expires_at <= utcnow():
            return False
        return True


class DataShareRequest(db.Model):
    __tablename__ = 'data_share_request'

    id = db.Column(db.Integer, primary_key=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False, default=lambda: uuid.uuid4().hex)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    denied_at = db.Column(db.DateTime(timezone=True), nullable=True)
    denial_reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    tutor = db.relationship('User', foreign_keys=[tutor_id])
    animal = db.relationship('Animal')
    clinic = db.relationship('Clinica')
    requester = db.relationship('User', foreign_keys=[requested_by_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])

    def is_pending(self):
        if self.status != 'pending':
            return False
        if self.expires_at and self.expires_at <= utcnow():
            return False
        return True


class DataShareLog(db.Model):
    __tablename__ = 'data_share_log'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    access_id = db.Column(db.Integer, db.ForeignKey('data_share_access.id'), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    event_type = db.Column(db.String(50), nullable=False)
    resource_type = db.Column(db.String(50), nullable=False)
    resource_id = db.Column(db.Integer, nullable=True)
    request_path = db.Column(db.String(255), nullable=True)
    request_ip = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    occurred_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)

    access = db.relationship('DataShareAccess', backref=db.backref('logs', cascade='all, delete-orphan'))
    actor = db.relationship('User', foreign_keys=[actor_id])



# Animal
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
class Transaction(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    from_user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    to_user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    type = db.Column(db.String(20))  # adoção, doação, venda, compra
    date = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    status = db.Column(db.String(20))  # pendente, concluída, cancelada

    from_user = db.relationship(
        'User',
        foreign_keys=[from_user_id],
        backref=db.backref('transacoes_enviadas', cascade='all, delete-orphan'),
    )
    to_user = db.relationship(
        'User',
        foreign_keys=[to_user_id],
        backref=db.backref('transacoes_recebidas', cascade='all, delete-orphan'),
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




class Consulta(db.Model):
    __table_args__ = (
        db.Index('ix_consulta_animal_status', 'animal_id', 'status'),
    )
    id = db.Column(db.Integer, primary_key=True)

    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )  # veterinário
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)
    health_plan_id = db.Column(db.Integer, db.ForeignKey('health_plan.id'), nullable=True)
    health_subscription_id = db.Column(
        db.Integer,
        db.ForeignKey('health_subscription.id', ondelete='SET NULL'),
        nullable=True,
    )
    authorization_status = db.Column(db.String(20), nullable=True)
    authorization_reference = db.Column(db.String(80), nullable=True)
    authorization_checked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    authorization_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    # Campos principais da consulta
    queixa_principal = db.Column(db.Text)
    historico_clinico = db.Column(db.Text)
    exame_fisico = db.Column(db.Text)
    suspeita_clinica = db.Column(db.String(160), index=True)
    conduta = db.Column(db.Text)
    prescricao = db.Column(db.Text)
    exames_solicitados = db.Column(db.Text)

    # Status da consulta (em andamento, finalizada, etc)
    status = db.Column(db.String(20), default='in_progress')
    finalizada_em = db.Column(db.DateTime(timezone=True), nullable=True)

    # Consulta de retorno
    retorno_de_id = db.Column(db.Integer, db.ForeignKey('consulta.id'))

    # Relacionamentos (se quiser acessar animal ou vet diretamente)
    animal = db.relationship('Animal', backref=db.backref('consultas', cascade='all, delete-orphan'))
    veterinario = db.relationship(
        'User',
        foreign_keys=[created_by],
        backref=db.backref('consultas', cascade='all, delete-orphan'),
    )
    clinica = db.relationship('Clinica', backref=db.backref('consultas', cascade='all, delete-orphan'))
    health_plan = db.relationship('HealthPlan', backref=db.backref('consultas', cascade='all, delete-orphan'))
    health_subscription = db.relationship(
        'HealthSubscription',
        backref=db.backref('consultas', cascade='all, delete-orphan'),
        foreign_keys=[health_subscription_id],
    )

    @property
    def total_orcamento(self):
        return sum(item.valor for item in self.orcamento_items)


class Orcamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    consulta_id = db.Column(db.Integer, db.ForeignKey('consulta.id'), nullable=True)
    descricao = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=now_in_brazil,
        onupdate=now_in_brazil,
        nullable=False,
    )
    status = db.Column(db.String(20), nullable=False, default='draft')
    email_sent_count = db.Column(db.Integer, nullable=False, default=0)
    whatsapp_sent_count = db.Column(db.Integer, nullable=False, default=0)
    payment_link = db.Column(db.Text, nullable=True)
    payment_reference = db.Column(db.String(120), nullable=True, index=True)
    payment_status = db.Column(db.String(20), nullable=True, index=True)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    clinica = db.relationship('Clinica', backref=db.backref('orcamentos', cascade='all, delete-orphan'))
    consulta = db.relationship('Consulta', backref=db.backref('orcamento', uselist=False))

    @property
    def total(self):
        return sum(item.valor for item in self.items)


class ServicoClinica(db.Model):
    __tablename__ = 'servico_clinica'

    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(120), nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    procedure_code = db.Column(db.String(64), nullable=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)
    clinica = db.relationship('Clinica', backref='servicos')


class OrcamentoItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    consulta_id = db.Column(db.Integer, db.ForeignKey('consulta.id'), nullable=True)
    orcamento_id = db.Column(db.Integer, db.ForeignKey('orcamento.id'), nullable=True)
    bloco_id = db.Column(db.Integer, db.ForeignKey('bloco_orcamento.id'), nullable=True)
    descricao = db.Column(db.String(120), nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    servico_id = db.Column(db.Integer, db.ForeignKey('servico_clinica.id'))
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    procedure_code = db.Column(db.String(64), nullable=True)
    coverage_id = db.Column(db.Integer, db.ForeignKey('health_coverage.id'), nullable=True)
    coverage_status = db.Column(db.String(20), default='pending')
    coverage_message = db.Column(db.Text, nullable=True)
    payer_type = db.Column(db.String(20), nullable=False, default='particular')

    consulta = db.relationship(
        'Consulta',
        backref=db.backref('orcamento_items', cascade='all, delete-orphan')
    )
    orcamento = db.relationship(
        'Orcamento',
        backref=db.backref('items', cascade='all, delete-orphan')
    )
    bloco = db.relationship(
        'BlocoOrcamento',
        backref=db.backref('itens', cascade='all, delete-orphan')
    )
    servico = db.relationship('ServicoClinica')
    clinica = db.relationship('Clinica', backref=db.backref('orcamento_items', cascade='all, delete-orphan'))
    coverage = db.relationship('HealthCoverage', backref=db.backref('orcamento_items', cascade='all, delete-orphan'))

    @property
    def effective_payer_type(self):
        return self.payer_type or 'particular'

    @property
    def payer_label(self):
        return 'Plano' if self.effective_payer_type == 'plan' else 'Particular'




class BlocoOrcamento(db.Model):
    __tablename__ = 'bloco_orcamento'

    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    data_criacao = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    discount_percent = db.Column(db.Numeric(5, 2), nullable=True)
    discount_value = db.Column(db.Numeric(10, 2), nullable=True)
    tutor_notes = db.Column(db.Text, nullable=True)
    net_total = db.Column(db.Numeric(10, 2), nullable=True)
    payment_status = db.Column(db.String(20), nullable=False, default='draft')
    payment_link = db.Column(db.Text, nullable=True)
    payment_reference = db.Column(db.String(120), nullable=True)

    animal = db.relationship('Animal', backref=db.backref('blocos_orcamento', cascade='all, delete-orphan', lazy=True))
    clinica = db.relationship('Clinica', backref=db.backref('blocos_orcamento', cascade='all, delete-orphan'))

    @property
    def total(self):
        return sum(item.valor for item in self.itens)

    @property
    def total_liquido(self):
        bruto = self.total or Decimal('0.00')
        desconto = self.discount_value or Decimal('0.00')
        if bruto is None:
            return Decimal('0.00')
        if desconto is None:
            return bruto
        return max(bruto - desconto, Decimal('0.00'))


# models.py

class BlocoPrescricao(db.Model):
    __tablename__ = 'bloco_prescricao'

    id = db.Column(db.Integer, primary_key=True)
    data_criacao = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    saved_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)

    prescricoes = db.relationship('Prescricao', backref='bloco', cascade='all, delete-orphan')
    instrucoes_gerais = db.Column(db.Text)

    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    animal = db.relationship('Animal', back_populates='blocos_prescricao')
    saved_by = db.relationship('User', foreign_keys=[saved_by_id])
    clinica = db.relationship('Clinica', backref=db.backref('blocos_prescricao', cascade='all, delete-orphan'))

class Prescricao(db.Model):
    __tablename__ = 'prescricao'

    id = db.Column(db.Integer, primary_key=True)
    bloco_id = db.Column(db.Integer, db.ForeignKey('bloco_prescricao.id'))  # pode manter se quiser blocos

    medicamento = db.Column(db.Text, nullable=False)
    dosagem = db.Column(db.Text)
    frequencia = db.Column(db.Text)
    duracao = db.Column(db.Text)
    observacoes = db.Column(db.Text)
    data_prescricao = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    # em Prescricao
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    animal = db.relationship('Animal', backref='prescricoes')  # em Prescricao

    def __repr__(self):
        return f'<Prescrição {self.medicamento} (ID: {self.id})>'


class Clinica(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
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


class NfseIssue(db.Model):
    """⚠️  DEPRECATED — não usar em código novo.

    Este modelo é o registro ORIGINAL de emissão NFS-e (stack legada
    services/nfse_service.py + app.py routes). Ele foi superado por
    `models.fiscal.FiscalDocument`, que:

      - Suporta NFS-e E NF-e no mesmo modelo (via `doc_type` enum).
      - Tem criptografia at-rest de `xml_signed` e `xml_authorized`
        (Fase 1.3).
      - Usa `reserve_next_number` com lock concorrente (Fase 1.2).
      - Expõe `emitter` (FiscalEmitter) — fonte única de CNPJ/IM por
        clínica, em vez dos campos soltos em Clinica.

    Roadmap:
      - Fase 1 (atual): FiscalDocument é o canônico para tudo NOVO.
        NfseIssue permanece read-only para não quebrar telas existentes.
      - Fase 2 (pós-NFS-e Nacional): data migration para consolidar as
        linhas legadas em FiscalDocument e dropar esta tabela.

    Se você precisa adicionar um campo aqui, PARE: adicione em
    FiscalDocument/FiscalEvent/FiscalCounter e migre o caso de uso.
    """

    __tablename__ = 'nfse_issues'
    id = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    internal_identifier = db.Column(db.String(80), nullable=True)
    rps = db.Column(db.String(50), nullable=True)
    numero_nfse = db.Column(db.String(50), nullable=True)
    serie = db.Column(db.String(50), nullable=True)
    protocolo = db.Column(db.String(80), nullable=True)
    status = db.Column(db.String(40), nullable=True)
    data_emissao = db.Column(db.DateTime(timezone=True), nullable=True)
    valor_total = db.Column(db.Numeric(12, 2), nullable=True)
    valor_iss = db.Column(db.Numeric(12, 2), nullable=True)
    tomador = db.Column(db.Text, nullable=True)
    prestador = db.Column(db.Text, nullable=True)
    xml_envio = db.Column(db.Text, nullable=True)
    xml_retorno = db.Column(db.Text, nullable=True)
    cancelada_em = db.Column(db.DateTime(timezone=True), nullable=True)
    cancelamento_motivo = db.Column(db.String(255), nullable=True)
    cancelamento_protocolo = db.Column(db.String(80), nullable=True)
    substituida_por_nfse = db.Column(db.String(50), nullable=True)
    substitui_nfse = db.Column(db.String(50), nullable=True)
    erro_codigo = db.Column(db.String(50), nullable=True)
    erro_mensagem = db.Column(db.Text, nullable=True)
    erro_detalhes = db.Column(db.Text, nullable=True)
    erro_em = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    clinica = db.relationship('Clinica', backref=db.backref('nfse_issues', cascade='all, delete-orphan'))
    eventos = db.relationship('NfseEvent', back_populates='nfse_issue', cascade='all, delete-orphan')
    xmls = db.relationship('NfseXml', back_populates='nfse_issue', cascade='all, delete-orphan')

    @property
    def tomador_payload(self) -> dict:
        if not self.tomador:
            return {}
        if isinstance(self.tomador, dict):
            return self.tomador
        try:
            payload = json.loads(self.tomador)
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @property
    def tutor_display_name(self) -> str | None:
        payload = self.tomador_payload
        return payload.get("tutor_nome") or payload.get("nome") or payload.get("tomador_nome")

    @property
    def tutor_documento(self) -> str | None:
        payload = self.tomador_payload
        return payload.get("tutor_documento") or payload.get("cpf_cnpj")

    @property
    def animal_display_name(self) -> str | None:
        payload = self.tomador_payload
        return payload.get("animal_nome")


class NfseEvent(db.Model):
    __tablename__ = 'nfse_events'
    id = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    nfse_issue_id = db.Column(db.Integer, db.ForeignKey('nfse_issues.id'), nullable=False)
    event_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(40), nullable=True)
    protocolo = db.Column(db.String(80), nullable=True)
    descricao = db.Column(db.Text, nullable=True)
    payload = db.Column(db.Text, nullable=True)
    data_evento = db.Column(db.DateTime(timezone=True), default=utcnow)

    clinica = db.relationship('Clinica', backref=db.backref('nfse_events', cascade='all, delete-orphan'))
    nfse_issue = db.relationship('NfseIssue', back_populates='eventos')


class NfseXml(db.Model):
    __tablename__ = 'nfse_xmls'
    id = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    nfse_issue_id = db.Column(db.Integer, db.ForeignKey('nfse_issues.id'), nullable=False)
    rps = db.Column(db.String(50), nullable=True)
    numero_nfse = db.Column(db.String(50), nullable=True)
    serie = db.Column(db.String(50), nullable=True)
    tipo = db.Column(db.String(30), nullable=False)
    protocolo = db.Column(db.String(80), nullable=True)
    # Conteúdo XML é armazenado criptografado por clínica.
    xml = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    clinica = db.relationship('Clinica', backref=db.backref('nfse_xmls', cascade='all, delete-orphan'))
    nfse_issue = db.relationship('NfseIssue', back_populates='xmls')

    def get_xml_plaintext(self) -> str:
        try:
            return decrypt_text_for_clinic(self.clinica_id, self.xml)
        except InvalidToken:
            return self.xml
        except MissingMasterKeyError:
            raise

# Convites para que veterinários se associem a uma clínica
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


class ClinicFinancialSnapshot(db.Model):
    __tablename__ = 'clinic_financial_snapshot'
    __table_args__ = (
        db.UniqueConstraint('clinic_id', 'month', name='uq_snapshot_clinic_month'),
    )

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    month = db.Column(db.Date, nullable=False, index=True)
    total_receitas_servicos = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    total_receitas_produtos = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    total_receitas_gerais = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    gerado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil)

    clinic = db.relationship(
        'Clinica',
        backref=db.backref('financial_snapshots', cascade='all, delete-orphan', lazy=True),
    )

    def refresh_totals(self):
        """Keep ``total_receitas_gerais`` in sync with service + product totals."""

        service = Decimal(self.total_receitas_servicos or 0)
        products = Decimal(self.total_receitas_produtos or 0)
        self.total_receitas_gerais = service + products
        return self.total_receitas_gerais


def _sync_snapshot_totals(_mapper, _connection, target):
    target.refresh_totals()


event.listen(ClinicFinancialSnapshot, 'before_insert', _sync_snapshot_totals)
event.listen(ClinicFinancialSnapshot, 'before_update', _sync_snapshot_totals)


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


class ClassifiedTransaction(db.Model):
    __tablename__ = 'classified_transactions'
    __table_args__ = (
        db.UniqueConstraint('clinic_id', 'raw_id', name='uq_classified_raw_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    date = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    month = db.Column(db.Date, nullable=False, index=True)
    origin = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    value = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    category = db.Column(db.String(80), nullable=False, index=True)
    subcategory = db.Column(db.String(80), nullable=True)
    raw_id = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)

    clinic = db.relationship(
        'Clinica',
        backref=db.backref('classified_transactions', cascade='all', lazy=True),
    )

    def __repr__(self):
        return f"<{self.origin} {self.category} R$ {self.value}>"


class AccountingAccount(db.Model):
    __tablename__ = 'accounting_accounts'
    __table_args__ = (
        db.UniqueConstraint('clinic_id', 'source_type', 'source_id', 'kind', name='uq_accounting_account_source'),
    )

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False, index=True)  # receivable/payable
    status = db.Column(db.String(20), nullable=False, default='open', server_default='open', index=True)
    description = db.Column(db.String(255), nullable=False)
    counterparty_name = db.Column(db.String(150), nullable=True)
    gross_amount = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    tax_amount = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    net_amount = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    issue_date = db.Column(db.Date, nullable=True, index=True)
    due_date = db.Column(db.Date, nullable=True, index=True)
    paid_at = db.Column(db.Date, nullable=True, index=True)
    source_type = db.Column(db.String(50), nullable=True)
    source_id = db.Column(db.Integer, nullable=True)
    source_reference = db.Column(db.String(120), nullable=True)
    bank_transaction_id = db.Column(
        db.Integer,
        db.ForeignKey('bank_statement_transactions.id', use_alter=True, name='fk_account_bank_transaction'),
        nullable=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=now_in_brazil,
        onupdate=now_in_brazil,
    )

    clinic = db.relationship(
        'Clinica',
        backref=db.backref('accounting_accounts', cascade='all, delete-orphan', lazy=True),
    )

    def mark_paid(self, paid_date=None, bank_transaction=None):
        self.status = 'paid'
        self.paid_at = paid_date or date.today()
        if bank_transaction is not None:
            self.bank_transaction_id = bank_transaction.id


class BankStatementTransaction(db.Model):
    __tablename__ = 'bank_statement_transactions'
    __table_args__ = (
        db.UniqueConstraint('clinic_id', 'fit_id', name='uq_bank_statement_fit_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    posted_at = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    memo = db.Column(db.String(255), nullable=True)
    fit_id = db.Column(db.String(120), nullable=True)
    matched_account_id = db.Column(db.Integer, db.ForeignKey('accounting_accounts.id'), nullable=True)
    match_confidence = db.Column(db.Numeric(5, 2), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil)

    clinic = db.relationship(
        'Clinica',
        backref=db.backref('bank_statement_transactions', cascade='all, delete-orphan', lazy=True),
    )
    matched_account = db.relationship(
        'AccountingAccount',
        foreign_keys=[matched_account_id],
        backref=db.backref('bank_matches', lazy=True),
    )


class PJPayment(db.Model):
    __tablename__ = 'pj_payments'
    __table_args__ = (
        db.CheckConstraint('valor >= 0', name='ck_pj_payments_valor_positive'),
        db.CheckConstraint("status IN ('pendente','pago')", name='ck_pj_payments_status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    prestador_nome = db.Column(db.String(150), nullable=False)
    prestador_cnpj = db.Column(db.String(20), nullable=False)
    nota_fiscal_numero = db.Column(db.String(80), nullable=True)
    tipo_prestador = db.Column(
        db.String(50),
        nullable=True,
        default='especialista',
        server_default='especialista',
    )
    plantao_horas = db.Column(db.Numeric(5, 2), nullable=True)
    valor = db.Column(db.Numeric(14, 2), nullable=False)
    data_servico = db.Column(db.Date, nullable=False)
    data_pagamento = db.Column(db.Date, nullable=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default='pendente',
        server_default='pendente',
    )
    observacoes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=now_in_brazil,
        onupdate=now_in_brazil,
    )

    clinica_id = synonym('clinic_id')

    clinic = db.relationship(
        'Clinica',
        backref=db.backref('pj_payments', cascade='all, delete-orphan', lazy=True),
    )

    def is_paid(self):
        return self.status == 'pago'

    def __repr__(self):
        return f"<PJPayment {self.prestador_nome} R$ {self.valor}>"


PLANTONISTA_ESCALA_STATUS_CHOICES = [
    ('agendado', 'Agendado'),
    ('confirmado', 'Confirmado'),
    ('realizado', 'Realizado'),
    ('cancelado', 'Cancelado'),
]


class PlantonistaEscala(db.Model):
    __tablename__ = 'plantonista_escalas'
    __table_args__ = (
        db.CheckConstraint('valor_previsto >= 0', name='ck_plantonista_valor_positive'),
    )

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    medico_id = db.Column(db.Integer, db.ForeignKey('veterinario.id'), nullable=True, index=True)
    medico_nome = db.Column(db.String(150), nullable=False)
    medico_cnpj = db.Column(db.String(20), nullable=True)
    turno = db.Column(db.String(80), nullable=False)
    inicio = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    fim = db.Column(db.DateTime(timezone=True), nullable=False)
    plantao_horas = db.Column(db.Numeric(5, 2), nullable=True)
    valor_previsto = db.Column(db.Numeric(14, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='agendado')
    nota_fiscal_recebida = db.Column(db.Boolean, nullable=False, default=False)
    retencao_validada = db.Column(db.Boolean, nullable=False, default=False)
    observacoes = db.Column(db.Text, nullable=True)
    realizado_em = db.Column(db.DateTime(timezone=True), nullable=True)
    pj_payment_id = db.Column(db.Integer, db.ForeignKey('pj_payments.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil, onupdate=now_in_brazil)

    clinic = db.relationship(
        'Clinica',
        backref=db.backref('plantonista_escalas', cascade='all, delete-orphan', lazy=True),
    )
    medico = db.relationship('Veterinario', backref=db.backref('escalas', lazy=True))
    pj_payment = db.relationship('PJPayment', backref=db.backref('plantao_escalas', lazy=True))

    @hybrid_property
    def horas_previstas(self):
        if self.plantao_horas is not None:
            return Decimal(str(self.plantao_horas))
        if not self.inicio or not self.fim:
            return Decimal('0.00')
        total_seconds = Decimal((self.fim - self.inicio).total_seconds())
        horas = total_seconds / Decimal('3600')
        return horas.quantize(Decimal('0.01'))

    @property
    def valor_pago(self):
        if self.pj_payment and self.pj_payment.status == 'pago':
            return self.pj_payment.valor or Decimal('0.00')
        return Decimal('0.00')

    @property
    def atrasado(self):
        if self.status in {'realizado', 'cancelado'}:
            return False
        referencia = self.fim or self.inicio
        if not referencia:
            return False
        return referencia < utcnow()

    def __repr__(self):
        return f"<PlantonistaEscala {self.medico_nome} {self.turno}>"


class PagamentoPlantonista(db.Model):
    __tablename__ = 'pagamento_plantonista'
    __table_args__ = (
        db.CheckConstraint('valor_total >= 0', name='ck_pagamento_plantonista_valor_positive'),
        db.CheckConstraint("status IN ('pendente','pago')", name='ck_pagamento_plantonista_status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    veterinario_id = db.Column(db.Integer, db.ForeignKey('veterinario.id'), nullable=False, index=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    mes_referencia = db.Column(db.Date, nullable=False)
    valor_total = db.Column(db.Numeric(14, 2), nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default='pendente',
        server_default='pendente',
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=now_in_brazil,
        onupdate=now_in_brazil,
    )

    veterinario = db.relationship('Veterinario', backref=db.backref('pagamentos_plantao', lazy=True))
    clinica = db.relationship('Clinica', backref=db.backref('pagamentos_plantao', lazy=True))

    def is_paid(self):
        return self.status == 'pago'

    def __repr__(self):
        return f"<PagamentoPlantonista {self.veterinario_id} {self.mes_referencia}>"


class CoberturaPlantonista(db.Model):
    __tablename__ = 'cobertura_plantonista'
    __table_args__ = (
        db.CheckConstraint('valor_hora >= 0', name='ck_cobertura_plantonista_valor_hora_positive'),
    )

    id = db.Column(db.Integer, primary_key=True)
    pagamento_id = db.Column(
        db.Integer,
        db.ForeignKey('pagamento_plantonista.id'),
        nullable=False,
        index=True,
    )
    data = db.Column(db.Date, nullable=False)
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fim = db.Column(db.Time, nullable=False)
    valor_hora = db.Column(db.Numeric(14, 2), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil)

    pagamento = db.relationship(
        'PagamentoPlantonista',
        backref=db.backref('coberturas', cascade='all, delete-orphan', lazy=True),
    )

    def __repr__(self):
        return f"<CoberturaPlantonista {self.data} {self.valor_hora}>"


class PlantaoModelo(db.Model):
    __tablename__ = 'plantao_modelos'

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    nome = db.Column(db.String(80), nullable=False)
    hora_inicio = db.Column(db.Time, nullable=True)
    duracao_horas = db.Column(db.Numeric(5, 2), nullable=False)
    medico_id = db.Column(db.Integer, db.ForeignKey('veterinario.id'), nullable=True, index=True)
    medico_nome = db.Column(db.String(150), nullable=True)
    medico_cnpj = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    clinic = db.relationship('Clinica', backref=db.backref('plantao_modelos', cascade='all, delete-orphan', lazy=True))
    medico = db.relationship('Veterinario', backref=db.backref('plantao_modelos', lazy=True))

    def __repr__(self):
        return f"<PlantaoModelo {self.nome} ({self.duracao_horas}h)>"

# Associação many-to-many entre veterinário e especialidade
veterinario_especialidade = db.Table(
    'veterinario_especialidade',
    db.Column('veterinario_id', db.Integer, db.ForeignKey('veterinario.id'), primary_key=True),
    db.Column('specialty_id', db.Integer, db.ForeignKey('specialty.id'), primary_key=True)
)

# Associação many-to-many entre veterinário e clínica
veterinario_clinica = db.Table(
    'veterinario_clinica',
    db.Column('veterinario_id', db.Integer, db.ForeignKey('veterinario.id'), primary_key=True),
    db.Column('clinica_id', db.Integer, db.ForeignKey('clinica.id'), primary_key=True),
)


class Specialty(db.Model):
    __tablename__ = 'specialty'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), unique=True, nullable=False)

    def __str__(self):
        return self.nome

class Veterinario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    crmv = db.Column(db.String(20), nullable=False)
    crmv_estado = db.Column(db.String(2), nullable=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'))
    public_profile_type = db.Column(db.String(20), nullable=False, default='profissional')
    public_visible = db.Column(db.Boolean, nullable=False, default=True)

    user = db.relationship('User', back_populates='veterinario', uselist=False)
    specialties = db.relationship('Specialty', secondary='veterinario_especialidade', backref='veterinarios')
    clinicas = db.relationship(
        'Clinica',
        secondary='veterinario_clinica',
        back_populates='veterinarios_associados',
    )

    @property
    def specialty_list(self):
        return ", ".join(s.nome for s in self.specialties)

    def __str__(self):
        return f"{self.user.name} (CRMV: {self.crmv})"


class VeterinarianMembership(db.Model):
    __tablename__ = 'veterinarian_membership'

    id = db.Column(db.Integer, primary_key=True)
    veterinario_id = db.Column(
        db.Integer,
        db.ForeignKey('veterinario.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
    )
    started_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    trial_ends_at = db.Column(db.DateTime(timezone=True), nullable=False)
    paid_until = db.Column(db.DateTime(timezone=True), nullable=True)
    last_payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=True)

    veterinario = db.relationship(
        'Veterinario',
        backref=db.backref('membership', cascade='all, delete-orphan', uselist=False),
    )
    last_payment = db.relationship('Payment', foreign_keys=[last_payment_id])

    def _now(self):
        return utcnow()

    @staticmethod
    def _as_timezone_aware(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    def ensure_trial_dates(self, trial_days: int = 30) -> None:
        """Guarantee that ``started_at`` and ``trial_ends_at`` are populated."""

        if self.started_at is None:
            self.started_at = self._now()
        if self.trial_ends_at is None:
            self.trial_ends_at = self.started_at + timedelta(days=trial_days)

    def restart_trial(self, trial_days: int = 30) -> None:
        """Start a fresh trial period from now."""

        now = self._now()
        self.started_at = now
        self.trial_ends_at = now + timedelta(days=trial_days)
        self.paid_until = None

    def is_trial_active(self) -> bool:
        trial_end = self._as_timezone_aware(self.trial_ends_at)
        if not trial_end:
            return False
        return self._now() <= trial_end

    def has_valid_payment(self) -> bool:
        paid_until = self._as_timezone_aware(self.paid_until)
        if not paid_until:
            return False
        return self._now() <= paid_until

    def is_active(self) -> bool:
        return self.is_trial_active() or self.has_valid_payment()

    @hybrid_property
    def is_active_flag(self) -> bool:
        return self.is_active()

    @is_active_flag.expression
    def is_active_flag(cls):  # type: ignore[override]
        return case(
            (cls.trial_ends_at >= func.now(), True),
            (cls.paid_until >= func.now(), True),
            else_=False,
        )

    def remaining_trial_days(self) -> int:
        if not self.trial_ends_at:
            return 0
        delta = self.trial_ends_at - self._now()
        return max(delta.days, 0)

    @property
    def status_label(self) -> str:
        if self.has_valid_payment():
            if self.paid_until:
                return f"Ativo — pago até {self.paid_until.strftime('%d/%m/%Y')}"
            return "Ativo — pagamento em dia"
        if self.is_trial_active():
            days = self.remaining_trial_days()
            return (
                "Período de teste ativo"
                if days <= 0
                else f"Teste ativo — {days} dia{'s' if days != 1 else ''} restantes"
            )
        return "Inativo"

    @property
    def last_payment_status(self):
        if self.last_payment and self.last_payment.status:
            return self.last_payment.status.value
        return None

    @property
    def last_payment_amount(self):
        if self.last_payment and self.last_payment.amount is not None:
            return float(self.last_payment.amount)
        return None


class VeterinarianSettings(db.Model):
    __tablename__ = 'veterinarian_settings'

    id = db.Column(db.Integer, primary_key=True)
    membership_price = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('60.00'))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    @classmethod
    def load(cls):
        """Return the singleton settings row, creating it if needed."""

        try:
            settings = cls.query.order_by(cls.id).first()
        except (OperationalError, ProgrammingError):
            db.session.rollback()
            return None

        if settings is None:
            default_price = Decimal(str(current_app.config.get('VETERINARIAN_MEMBERSHIP_PRICE', 60.00)))
            settings = cls(membership_price=default_price)
            db.session.add(settings)
            try:
                db.session.commit()
            except Exception:  # noqa: BLE001
                db.session.rollback()
                return None

        return settings

    @classmethod
    def membership_price_amount(cls) -> Decimal:
        """Return the configured membership price as a Decimal."""

        settings = cls.load()
        if settings and settings.membership_price is not None:
            return Decimal(settings.membership_price)

        return Decimal(str(current_app.config.get('VETERINARIAN_MEMBERSHIP_PRICE', 60.00)))

class VetSchedule(db.Model):
    __tablename__ = 'vet_schedule'
    id = db.Column(db.Integer, primary_key=True)
    veterinario_id = db.Column(db.Integer, db.ForeignKey('veterinario.id'), nullable=False)
    dia_semana = db.Column(db.String(20), nullable=False)
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fim = db.Column(db.Time, nullable=False)
    intervalo_inicio = db.Column(db.Time, nullable=True)
    intervalo_fim = db.Column(db.Time, nullable=True)

    veterinario = db.relationship('Veterinario', backref='horarios')


class Appointment(db.Model):
    __tablename__ = 'appointment'

    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    tutor_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    veterinario_id = db.Column(db.Integer, db.ForeignKey('veterinario.id'), nullable=False)
    scheduled_at = db.Column(db.DateTime(timezone=True), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='scheduled')
    kind = db.Column(db.String(20), nullable=False, default='general')
    notes = db.Column(db.Text, nullable=True)
    consulta_id = db.Column(db.Integer, db.ForeignKey('consulta.id'), nullable=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    animal = db.relationship(
        'Animal',
        backref=db.backref('appointments', cascade='all, delete-orphan'),
    )
    tutor = db.relationship(
        'User',
        foreign_keys=[tutor_id],
        backref=db.backref('appointments', cascade='all, delete-orphan'),
    )
    veterinario = db.relationship(
        'Veterinario',
        backref=db.backref('appointments', cascade='all, delete-orphan'),
    )
    clinica = db.relationship('Clinica', backref=db.backref('appointments', cascade='all, delete-orphan'))
    consulta = db.relationship(
        'Consulta',
        backref=db.backref('appointment', uselist=False),
        uselist=False,
    )
    creator = db.relationship(
        'User',
        foreign_keys=[created_by],
        backref='created_appointments',
    )

    @classmethod
    def has_active_subscription(cls, animal_id, tutor_id):
        from models import HealthSubscription

        return (
            HealthSubscription.query
            .filter_by(animal_id=animal_id, user_id=tutor_id, active=True)
            .first()
            is not None
        )

    @staticmethod
    def _validate_subscription(mapper, connection, target):
        if current_app.config.get('REQUIRE_HEALTH_SUBSCRIPTION_FOR_APPOINTMENT', False):
            if not type(target).has_active_subscription(target.animal_id, target.tutor_id):
                raise ValueError(
                    'Animal does not have an active health subscription for this tutor.'
                )

    @staticmethod
    def _set_clinica(mapper, connection, target):
        """Populate clinica_id from veterinarian or animal if not set."""
        if not target.clinica_id and target.veterinario_id:
            vet = db.session.get(Veterinario, target.veterinario_id)
            if vet and vet.clinica_id:
                target.clinica_id = vet.clinica_id
        if not target.clinica_id and target.animal_id:
            animal = db.session.get(Animal, target.animal_id)
            if animal and animal.clinica_id:
                target.clinica_id = animal.clinica_id


event.listen(Appointment, 'before_insert', Appointment._validate_subscription)
event.listen(Appointment, 'before_update', Appointment._validate_subscription)
event.listen(Appointment, 'before_insert', Appointment._set_clinica)
event.listen(Appointment, 'before_update', Appointment._set_clinica)


def _create_veterinarian_membership(mapper, connection, target):
    """Ensure every veterinarian profile starts with a membership record."""

    trial_days = current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30)
    now = utcnow()
    membership_row = connection.execute(
        VeterinarianMembership.__table__.select().where(
            VeterinarianMembership.veterinario_id == target.id
        )
    ).first()
    if membership_row is None:
        connection.execute(
            VeterinarianMembership.__table__.insert().values(
                veterinario_id=target.id,
                started_at=now,
                trial_ends_at=now + timedelta(days=trial_days),
            )
        )


event.listen(Veterinario, 'after_insert', _create_veterinarian_membership, propagate=True)

# Agendamento de exames
class ExamAppointment(db.Model):
    __tablename__ = 'exam_appointment'

    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    specialist_id = db.Column(db.Integer, db.ForeignKey('veterinario.id'), nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    exam_name = db.Column(db.String(120))
    scheduled_at = db.Column(db.DateTime(timezone=True), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    request_time = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    confirm_by = db.Column(db.DateTime(timezone=True))

    animal = db.relationship(
        'Animal',
        backref=db.backref('exam_appointments', cascade='all, delete-orphan'),
    )
    specialist = db.relationship(
        'Veterinario',
        backref=db.backref('exam_appointments', cascade='all, delete-orphan'),
    )
    requester = db.relationship(
        'User',
        backref=db.backref('requested_exam_appointments', cascade='all, delete-orphan'),
        foreign_keys=[requester_id]
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.request_time:
            self.request_time = utcnow()
        if not self.confirm_by:
            self.confirm_by = (self.request_time or utcnow()) + timedelta(hours=2)

    @property
    def status_display(self):
        if self.status == 'confirmed':
            return 'Aceito'
        if self.status == 'canceled':
            return 'Cancelado'
        if self.confirm_by:
            now = utcnow()
            if self.confirm_by.tzinfo is None:
                now = now.replace(tzinfo=None)
            if now > self.confirm_by:
                return 'Prazo expirado'
        return 'Aguardando aceitação'


class AppointmentRequest(db.Model):
    """Solicitação de agendamento feita pelo tutor, sem expor a agenda do profissional.

    O tutor envia data/horário preferidos e o profissional confirma (gerando um
    ``Appointment`` real) ou recusa. Isola o fluxo pedido→confirmação para
    consultas, exames e vacinas, sem tocar na agenda existente — o tutor nunca
    vê compromissos de outros pacientes nem dados internos da clínica.
    """
    __tablename__ = 'appointment_request'

    id = db.Column(db.Integer, primary_key=True)
    tutor_id = db.Column(
        db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True
    )
    animal_id = db.Column(
        db.Integer, db.ForeignKey('animal.id', ondelete='CASCADE'), nullable=False
    )
    veterinario_id = db.Column(
        db.Integer, db.ForeignKey('veterinario.id', ondelete='CASCADE'), nullable=False, index=True
    )
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)

    kind = db.Column(db.String(20), nullable=False, default='consulta')   # consulta/exame/vacina
    mode = db.Column(db.String(20), nullable=False, default='clinica')    # clinica/domicilio
    preferred_date = db.Column(db.Date, nullable=False)
    preferred_time = db.Column(db.Time, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    response_note = db.Column(db.Text, nullable=True)
    appointment_id = db.Column(
        db.Integer, db.ForeignKey('appointment.id', ondelete='SET NULL'), nullable=True
    )

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    responded_at = db.Column(db.DateTime(timezone=True), nullable=True)

    tutor = db.relationship(
        'User', foreign_keys=[tutor_id],
        backref=db.backref('appointment_requests', cascade='all, delete-orphan'),
    )
    animal = db.relationship(
        'Animal', backref=db.backref('appointment_requests', cascade='all, delete-orphan'),
    )
    veterinario = db.relationship(
        'Veterinario', backref=db.backref('appointment_requests', cascade='all, delete-orphan'),
    )
    clinica = db.relationship('Clinica')
    appointment = db.relationship('Appointment', foreign_keys=[appointment_id])

    KIND_LABELS = {'consulta': 'Consulta', 'exame': 'Exame', 'vacina': 'Vacina'}
    MODE_LABELS = {'clinica': 'Na clínica', 'domicilio': 'A domicílio'}
    STATUS_LABELS = {
        'pending': 'Aguardando confirmação',
        'confirmed': 'Confirmado',
        'declined': 'Recusado',
        'cancelled': 'Cancelado',
    }

    @property
    def kind_label(self):
        return self.KIND_LABELS.get(self.kind, self.kind)

    @property
    def mode_label(self):
        return self.MODE_LABELS.get(self.mode, self.mode)

    @property
    def status_display(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def is_pending(self):
        return self.status == 'pending'


# Associação many-to-many entre eventos e colaboradores
EventoColaboradores = db.Table(
    'evento_colaboradores',
    db.Column('evento_id', db.Integer, db.ForeignKey('agenda_evento.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)


class AgendaEvento(db.Model):
    __tablename__ = 'agenda_evento'

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(120), nullable=False)
    inicio = db.Column(db.DateTime(timezone=True), nullable=False)
    fim = db.Column(db.DateTime(timezone=True), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    responsavel_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)

    responsavel = db.relationship('User', back_populates='eventos_responsavel', foreign_keys=[responsavel_id])
    clinica = db.relationship('Clinica', back_populates='eventos')
    colaboradores = db.relationship('User', secondary=EventoColaboradores, back_populates='eventos_colaborador')

    def __repr__(self):
        return f'<AgendaEvento {self.titulo}>'

class Medicamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    classificacao = db.Column(db.String(100))  # 🆕 antibiótico, anti-inflamatório, etc.
    principio_ativo = db.Column(db.String(100))  # opcional
    via_administracao = db.Column(db.String(50))  # oral, IM, IV...
    dosagem_recomendada = db.Column(db.Text)  # Ex: 5 mg/kg SID
    frequencia = db.Column(db.Text)  # Ex: SID, BID, TID
    duracao_tratamento = db.Column(db.Text)  # Ex: 7 dias
    observacoes = db.Column(db.Text)  # para contraindicações, interações, etc.
    bula = db.Column(db.Text)  # 🆕 Texto completo da bula, opcional
    conteudo_estruturado = db.Column(db.JSON)  # seções clínicas separadas para UI

    # Sinaliza para quais espécies este item é mais relevante.
    # Valores: 'CG' (cães/gatos), 'BE' (bovinos/equinos), 'AMBOS', 'OUTRO'.
    # NULL = não classificado. Usado APENAS para re-ranquear a busca; nenhum item
    # é escondido ou filtrado por causa deste campo.
    species_scope = db.Column(db.String(20), index=True, nullable=True)

    # Produto "canônico" no VetSmart que representa este PA
    # (ex.: "Prednisona" PA genérico, id=1970)
    vetsmart_produto_id = db.Column(db.Integer, index=True)

    created_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )

    apresentacoes = db.relationship('ApresentacaoMedicamento', backref='medicamento', cascade='all, delete-orphan')
    doses = db.relationship('DoseMedicamento', backref='medicamento', cascade='all, delete-orphan', order_by='DoseMedicamento.id')

    def __str__(self):
        return self.nome

class ApresentacaoMedicamento(db.Model):
    __tablename__ = 'apresentacao_medicamento'
    id = db.Column(db.Integer, primary_key=True)
    medicamento_id = db.Column(db.Integer, db.ForeignKey('medicamento.id'), nullable=False)

    forma = db.Column(db.String(50), nullable=False)          # cápsula, líquido, etc.
    concentracao = db.Column(db.String(100), nullable=False)  # Ex: 50 mg/mL, 500 mg/cápsula

    # Campos numéricos para cálculo de dose
    nome_variante        = db.Column(db.String(100))          # "Advocate Cães até 4 kg"
    concentracao_valor   = db.Column(db.Numeric(12, 3))       # 250
    concentracao_unidade = db.Column(db.String(20))           # 'mg' | 'mg/ml' | 'UI' | '%'
    volume_valor         = db.Column(db.Numeric(12, 3))       # 10 (un) ou 50 (ml)
    volume_unidade       = db.Column(db.String(20))           # 'un' | 'ml' | 'g'

    # Nome do produto comercial associado (ex: "Sec Lac" para metergolina Agener).
    # Quando preenchido, permite busca pelo nome comercial no autocomplete e
    # exibe apenas as apresentações desta marca ao pesquisar por ela.
    nome_comercial       = db.Column(db.String(150))

    # Fabricante específico desta apresentação.
    # Um mesmo Medicamento (ex.: "Prednisona") pode ter apresentações
    # da LigVet, Animalia, genérico, etc.
    fabricante           = db.Column(db.String(150))

    # Origem no VetSmart (produto comercial de onde veio a apresentação).
    vetsmart_produto_id  = db.Column(db.Integer, index=True)

    def __str__(self):
        return f"{self.medicamento.nome} – {self.forma} ({self.concentracao})"


class DoseMedicamento(db.Model):
    __tablename__ = 'dose_medicamento'
    id = db.Column(db.Integer, primary_key=True)
    medicamento_id = db.Column(db.Integer, db.ForeignKey('medicamento.id', ondelete='CASCADE'), nullable=False)

    especie = db.Column(db.String(80))          # Ex: "Cães", "Gatos", "Cães e Gatos"
    faixa_peso = db.Column(db.String(80))       # Ex: "Até 4 kg", "Entre 10 e 25 kg"
    via = db.Column(db.String(80))              # Ex: "Oral", "Tópica"
    dose = db.Column(db.String(200))            # Ex: "20 - 30 mg/kg", "0,4 mL/animal"
    frequencia = db.Column(db.String(120))      # Ex: "A cada 12 horas"
    duracao = db.Column(db.String(120))         # Ex: "7 dias"
    observacao = db.Column(db.Text)             # Notas/modo de usar

    # Campos numéricos para cálculo automático
    especie_code       = db.Column(db.String(10))              # 'CAES' | 'GATOS' | 'AMBOS' | 'OUTRO'
    peso_min_kg        = db.Column(db.Numeric(8, 2))           # null = sem mínimo
    peso_max_kg        = db.Column(db.Numeric(8, 2))           # null = sem máximo
    dose_min           = db.Column(db.Numeric(12, 3))
    dose_max           = db.Column(db.Numeric(12, 3))
    dose_unidade       = db.Column(db.String(30))              # 'MG_KG'|'ML_KG'|'UI_KG'|'MG_ANIMAL'|...
    intervalo_horas    = db.Column(db.Integer)                 # valor único (retrocompat)
    intervalo_min_horas = db.Column(db.Integer)               # null se não há faixa
    intervalo_max_horas = db.Column(db.Integer)               # null se não há faixa
    duracao_min_dias   = db.Column(db.Integer)
    duracao_max_dias   = db.Column(db.Integer)
    dose_raw_text      = db.Column(db.Text)                    # trecho original do VetSmart
    fonte              = db.Column(db.String(15), default='HUMANO')  # 'SCRAPER'|'LLM'|'HUMANO'
    confianca          = db.Column(db.String(10), default='MEDIA')   # 'ALTA'|'MEDIA'|'BAIXA'

    # Indicação clínica desta dose (Alergia, Imunossupressão, Dermatite atópica, ...).
    # NULL quando o parser não consegue inferir com confiança — nesse caso o
    # calculador de dose exibe todas as doses disponíveis e deixa o vet escolher.
    indicacao          = db.Column(db.String(120), index=True)

    def __str__(self):
        partes = [p for p in [self.especie, self.faixa_peso, self.dose] if p]
        return " · ".join(partes) or f"Dose #{self.id}"


class PrescricaoAliasMedicamento(db.Model):
    """Mapeia texto exato de prescrição histórica ao medicamento canônico.

    Permite que nomes como 'Dipirona – 500 mg/mL, gotas' (formato VetSmart com em-dash)
    sejam resolvidos ao ID correto sem match exato no nome do Medicamento.
    confianca: 'exato' | 'normalizado' | 'prefixo' | 'variante' | 'substring' | 'manual' | 'sem_match'
    """
    __tablename__ = 'prescricao_alias_medicamento'
    id = db.Column(db.Integer, primary_key=True)
    nome_prescrito = db.Column(db.Text, nullable=False, unique=True)
    medicamento_id = db.Column(
        db.Integer,
        db.ForeignKey('medicamento.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    confianca = db.Column(db.String(20), nullable=False, default='auto')
    criado_em = db.Column(db.DateTime(timezone=True), server_default=db.func.now())


class MedicamentoFavorito(db.Model):
    """Medicamentos marcados como favoritos por um veterinário."""
    __tablename__ = 'medicamento_favorito'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    medicamento_id = db.Column(
        db.Integer,
        db.ForeignKey('medicamento.id', ondelete='CASCADE'),
        nullable=False,
    )
    criado_em = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
    )

    __table_args__ = (
        db.UniqueConstraint('user_id', 'medicamento_id', name='uq_fav_user_med'),
    )


class ExameModelo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)  # ex: Hemograma, Raio-X...
    justificativa = db.Column(db.Text)
    # Ver Medicamento.species_scope (CG/BE/AMBOS/OUTRO) — usado p/ re-ranquear busca.
    species_scope = db.Column(db.String(20), index=True, nullable=True)
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )

class BlocoExames(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)  # <- novo campo
    observacoes_gerais = db.Column(db.Text)
    data_criacao = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    animal = db.relationship('Animal', backref=db.backref('blocos_exames', cascade='all, delete-orphan', lazy=True))
    exames = db.relationship('ExameSolicitado', backref='bloco', cascade='all, delete-orphan')

class ExameSolicitado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bloco_id = db.Column(db.Integer, db.ForeignKey('bloco_exames.id'), nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    justificativa = db.Column(db.Text)
    status = db.Column(db.String(20), default='pendente')
    resultado = db.Column(db.Text, nullable=True)
    performed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    laudo_url = db.Column(db.String(500), nullable=True)
    laudo_filename = db.Column(db.String(255), nullable=True)
    laudo_uploaded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    laudo_message = db.Column(db.Text, nullable=True)


class ExameImagem(db.Model):
    __tablename__ = 'exame_imagem'

    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False, index=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    clinica_requisitante_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True, index=True)
    profissional_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    documento_id = db.Column(db.Integer, db.ForeignKey('animal_documento.id', ondelete='SET NULL'), nullable=True)
    exame_solicitado_id = db.Column(db.Integer, db.ForeignKey('exame_solicitado.id', ondelete='SET NULL'), nullable=True)
    tipo_exame = db.Column(db.String(160), nullable=False)
    data_exame = db.Column(db.Date, nullable=True)
    titulo = db.Column(db.String(200), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    impressao_diagnostica = db.Column(db.Text, nullable=True)
    profissional_nome = db.Column(db.String(160), nullable=True)
    profissional_crmv = db.Column(db.String(60), nullable=True)
    arquivo_pdf_url = db.Column(db.String(500), nullable=True)
    arquivo_pdf_filename = db.Column(db.String(255), nullable=True)
    arquivo_pdf_content_type = db.Column(db.String(120), nullable=True)
    arquivo_pdf_size = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(40), nullable=False, default='rascunho', index=True)
    liberado_para_clinica = db.Column(db.Boolean, nullable=False, default=False)
    liberado_para_tutor = db.Column(db.Boolean, nullable=False, default=False)
    data_liberacao_clinica = db.Column(db.DateTime(timezone=True), nullable=True)
    data_liberacao_tutor = db.Column(db.DateTime(timezone=True), nullable=True)
    usuario_que_liberou_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, onupdate=now_in_brazil, nullable=False)

    animal = db.relationship('Animal', backref=db.backref('exames_imagem', cascade='all, delete-orphan'))
    tutor = db.relationship('User', foreign_keys=[tutor_id], backref=db.backref('exames_imagem_tutor', cascade='all, delete-orphan'))
    clinica_requisitante = db.relationship('Clinica', backref=db.backref('exames_imagem_recebidos', cascade='all, delete-orphan'))
    profissional = db.relationship('User', foreign_keys=[profissional_id])
    documento = db.relationship('AnimalDocumento', foreign_keys=[documento_id])
    exame_solicitado = db.relationship('ExameSolicitado', foreign_keys=[exame_solicitado_id])
    usuario_que_liberou = db.relationship('User', foreign_keys=[usuario_que_liberou_id])


class ExameImagemPdfAccessLog(db.Model):
    __tablename__ = 'exame_imagem_pdf_access_log'

    id = db.Column(db.Integer, primary_key=True)
    exame_imagem_id = db.Column(db.Integer, db.ForeignKey('exame_imagem.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    accessed_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    action = db.Column(db.String(40), nullable=False, default='view')
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)

    exame = db.relationship('ExameImagem', backref=db.backref('pdf_access_logs', cascade='all, delete-orphan'))
    user = db.relationship('User')


class ProtocoloClinico(db.Model):
    __tablename__ = 'protocolo_clinico'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    suspeita_principal = db.Column(db.String(160), nullable=False, index=True)
    especie = db.Column(db.String(40), nullable=True, index=True)
    sinais_gatilho = db.Column(db.Text)
    conduta_sugerida = db.Column(db.Text)
    orientacoes_tutor = db.Column(db.Text)
    alertas = db.Column(db.Text)
    prioridade = db.Column(db.Integer, nullable=False, default=100)
    versao = db.Column(db.Integer, nullable=False, default=1)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=True)
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=now_in_brazil,
        onupdate=now_in_brazil,
        nullable=False,
    )

    clinica = db.relationship('Clinica', backref=db.backref('protocolos_clinicos', cascade='all, delete-orphan'))
    criador = db.relationship('User', foreign_keys=[created_by])
    exames_sugeridos = db.relationship(
        'ProtocoloClinicoExame',
        backref='protocolo',
        cascade='all, delete-orphan',
        order_by='ProtocoloClinicoExame.prioridade, ProtocoloClinicoExame.id',
    )
    medicamentos_sugeridos = db.relationship(
        'ProtocoloClinicoMedicamento',
        backref='protocolo',
        cascade='all, delete-orphan',
        order_by='ProtocoloClinicoMedicamento.prioridade, ProtocoloClinicoMedicamento.id',
    )
    retornos_sugeridos = db.relationship(
        'ProtocoloClinicoRetorno',
        backref='protocolo',
        cascade='all, delete-orphan',
        order_by='ProtocoloClinicoRetorno.prioridade, ProtocoloClinicoRetorno.id',
    )

    @property
    def taxa_aceitacao(self):
        auditorias = getattr(self, 'auditorias_sugestao', None) or []
        mostradas = sum(1 for item in auditorias if item.acao == 'shown')
        aceitas = sum(1 for item in auditorias if item.acao == 'accepted')
        if mostradas <= 0:
            return None
        return round((aceitas / mostradas) * 100, 1)


class ProtocoloClinicoExame(db.Model):
    __tablename__ = 'protocolo_clinico_exame'

    id = db.Column(db.Integer, primary_key=True)
    protocolo_id = db.Column(
        db.Integer,
        db.ForeignKey('protocolo_clinico.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    nome = db.Column(db.String(120), nullable=False)
    justificativa = db.Column(db.Text)
    prioridade = db.Column(db.Integer, nullable=False, default=0)


class ProtocoloClinicoMedicamento(db.Model):
    __tablename__ = 'protocolo_clinico_medicamento'

    id = db.Column(db.Integer, primary_key=True)
    protocolo_id = db.Column(
        db.Integer,
        db.ForeignKey('protocolo_clinico.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    medicamento_id = db.Column(
        db.Integer,
        db.ForeignKey('medicamento.id', ondelete='SET NULL'),
        nullable=True,
    )
    nome_medicamento = db.Column(db.String(120), nullable=True)
    justificativa = db.Column(db.Text)
    dosagem_texto = db.Column(db.Text)
    frequencia_texto = db.Column(db.Text)
    duracao_texto = db.Column(db.Text)
    observacoes = db.Column(db.Text)
    indicacao = db.Column(db.String(120))
    prioridade = db.Column(db.Integer, nullable=False, default=0)

    medicamento = db.relationship('Medicamento')

    @property
    def nome_exibicao(self):
        if self.nome_medicamento:
            return self.nome_medicamento
        if self.medicamento:
            return self.medicamento.nome
        return ''


class ProtocoloClinicoRetorno(db.Model):
    __tablename__ = 'protocolo_clinico_retorno'

    id = db.Column(db.Integer, primary_key=True)
    protocolo_id = db.Column(
        db.Integer,
        db.ForeignKey('protocolo_clinico.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    prazo_min_dias = db.Column(db.Integer, nullable=True)
    prazo_max_dias = db.Column(db.Integer, nullable=True)
    tipo_retorno = db.Column(db.String(40), nullable=False, default='retorno')
    objetivo = db.Column(db.Text)
    gatilhos_antecipacao = db.Column(db.Text)
    prioridade = db.Column(db.Integer, nullable=False, default=0)


class AuditoriaSugestaoClinica(db.Model):
    __tablename__ = 'auditoria_sugestao_clinica'

    id = db.Column(db.Integer, primary_key=True)
    consulta_id = db.Column(
        db.Integer,
        db.ForeignKey('consulta.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    protocolo_id = db.Column(
        db.Integer,
        db.ForeignKey('protocolo_clinico.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    actor_user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    tipo_item = db.Column(db.String(30), nullable=False, index=True)
    acao = db.Column(db.String(30), nullable=False, index=True)
    titulo_item = db.Column(db.String(200), nullable=True)
    justificativa = db.Column(db.Text)
    payload = db.Column(db.JSON)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)

    consulta = db.relationship('Consulta', backref=db.backref('auditorias_sugestao_clinica', cascade='all, delete-orphan'))
    protocolo = db.relationship('ProtocoloClinico', backref=db.backref('auditorias_sugestao', lazy=True))
    actor = db.relationship('User', foreign_keys=[actor_user_id])


class VacinaModelo(db.Model):
    __tablename__ = 'vacina_modelo'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(50))  # Opcional, mas útil para o frontend
    fabricante = db.Column(db.String(100))
    doses_totais = db.Column(db.Integer)
    intervalo_dias = db.Column(db.Integer)
    frequencia = db.Column(db.String(50))
    # Ver Medicamento.species_scope (CG/BE/AMBOS/OUTRO) — usado p/ re-ranquear busca.
    species_scope = db.Column(db.String(20), index=True, nullable=True)
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )

    def __repr__(self):
        return (
            f"<VacinaModelo {self.nome} fabricante={self.fabricante} "
            f"doses={self.doses_totais} intervalo={self.intervalo_dias} "
            f"frequencia={self.frequencia}>"
        )


class Vacina(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)

    nome = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(50))  # Campanha, Obrigatória, Reforço
    fabricante = db.Column(db.String(100))
    doses_totais = db.Column(db.Integer)
    intervalo_dias = db.Column(db.Integer)
    frequencia = db.Column(db.String(50))
    aplicada = db.Column(db.Boolean, default=False)
    aplicada_em = db.Column(db.Date)        # Data da aplicação
    observacoes = db.Column(db.Text)
    aplicada = db.Column(db.Boolean, default=False)
    aplicada_em = db.Column(db.Date)
    aplicada_por = db.Column(db.Integer, db.ForeignKey('user.id'))
    criada_em = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    data = synonym('aplicada_em')

    lote = db.Column(db.String(64), nullable=True)

    aplicador = db.relationship('User', foreign_keys=[aplicada_por])

    @property
    def proxima_dose(self):
        if self.aplicada and self.aplicada_em and self.intervalo_dias:
            return self.aplicada_em + timedelta(days=self.intervalo_dias)
        return None

    @property
    def veterinario(self):
        vet_user = self.aplicador
        if not vet_user:
            return None
        crmv = getattr(getattr(vet_user, 'veterinario', None), 'crmv', None)
        if crmv:
            return f"{vet_user.name} (CRMV {crmv})"
        return vet_user.name

    # Registro de quem cadastrou a vacina
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
    )


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


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    channel = db.Column(db.String(20), nullable=False)
    kind = db.Column(db.String(50), nullable=True)
    sent_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    user = db.relationship('User', backref=db.backref('notifications', cascade='all, delete-orphan'))


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


class DeliveryResearchContact(db.Model):
    __tablename__ = 'delivery_research_contact'

    id = db.Column(db.Integer, primary_key=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, unique=True, index=True)
    sent = db.Column(db.Boolean, nullable=False, default=False)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    sent_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    replied = db.Column(db.Boolean, nullable=False, default=False)
    replied_at = db.Column(db.DateTime(timezone=True), nullable=True)
    replied_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    recorded = db.Column(db.Boolean, nullable=False, default=False)
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    do_not_send = db.Column(db.Boolean, nullable=False, default=False)
    do_not_send_at = db.Column(db.DateTime(timezone=True), nullable=True)
    do_not_send_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    interest_answer = db.Column(db.String(20), nullable=True)
    current_food = db.Column(db.String(255), nullable=True)
    bag_size = db.Column(db.String(80), nullable=True)
    price_paid = db.Column(db.String(80), nullable=True)
    purchase_channel = db.Column(db.String(120), nullable=True)
    duration_estimate = db.Column(db.String(120), nullable=True)
    response_notes = db.Column(db.Text, nullable=True)
    response_collected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    tutor = db.relationship('User', foreign_keys=[tutor_id], backref=db.backref('delivery_research_contact', uselist=False, cascade='all, delete-orphan'))
    sent_by = db.relationship('User', foreign_keys=[sent_by_id])
    replied_by = db.relationship('User', foreign_keys=[replied_by_id])
    recorded_by = db.relationship('User', foreign_keys=[recorded_by_id])
    do_not_send_by = db.relationship('User', foreign_keys=[do_not_send_by_id])


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
PRODUCT_CATEGORIES = [
    {"value": "racao",       "label": "Ração",            "icon": "fa-bowl-food"},
    {"value": "petisco",     "label": "Petiscos",         "icon": "fa-bone"},
    {"value": "brinquedo",   "label": "Brinquedos",       "icon": "fa-baseball"},
    {"value": "higiene",     "label": "Higiene & Beleza", "icon": "fa-pump-soap"},
    {"value": "acessorio",   "label": "Acessórios",       "icon": "fa-tag"},
    {"value": "medicamento", "label": "Medicamentos",     "icon": "fa-pills"},
]
PRODUCT_CATEGORY_VALUES = [c["value"] for c in PRODUCT_CATEGORIES]
PRODUCT_CATEGORY_LABELS = {c["value"]: c["label"] for c in PRODUCT_CATEGORIES}
# Opções para SelectField, com entrada vazia para "sem categoria".
PRODUCT_CATEGORY_CHOICES = [("", "— Sem categoria —")] + [
    (c["value"], c["label"]) for c in PRODUCT_CATEGORIES
]


class ProductCategory(db.Model):
    """Categoria de produto da Loja — gerenciável pelo admin.

    Substitui a antiga lista fixa em código: novas categorias podem ser
    adicionadas conforme a necessidade pelo painel administrativo. A constante
    ``PRODUCT_CATEGORIES`` permanece apenas como semente inicial desta tabela
    (e como fallback caso a tabela ainda não exista / esteja vazia).
    """
    __tablename__ = "product_category"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(40), unique=True, nullable=False)
    label = db.Column(db.String(60), nullable=False)
    icon = db.Column(db.String(40), default="fa-tag")
    position = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True, nullable=False)

    @property
    def value(self):
        """Alias usado pelos templates de chips (mesma semântica do slug)."""
        return self.slug

    def __str__(self):
        return self.label or self.slug

    def __repr__(self):
        return f"<ProductCategory {self.slug}>"


def _seed_product_categories():
    """Categorias semente como objetos transitórios (não persistidos).

    Usado como fallback quando a tabela ``product_category`` ainda não existe
    (antes da migração) ou está vazia, garantindo que a Loja nunca quebre.
    """
    return [
        ProductCategory(slug=c["value"], label=c["label"], icon=c["icon"],
                        position=i, active=True)
        for i, c in enumerate(PRODUCT_CATEGORIES)
    ]


def get_active_product_categories():
    """Categorias ativas, ordenadas para exibição (chips/select)."""
    try:
        cats = (
            ProductCategory.query
            .filter_by(active=True)
            .order_by(ProductCategory.position, ProductCategory.label)
            .all()
        )
    except Exception:
        # Tabela ainda não migrada: desfaz a transação abortada e usa a semente.
        try:
            db.session.rollback()
        except Exception:
            pass
        cats = []
    return cats or _seed_product_categories()


def product_category_choices():
    """Choices para SelectField, com entrada vazia para 'sem categoria'."""
    return [("", "— Sem categoria —")] + [
        (c.slug, c.label) for c in get_active_product_categories()
    ]


def product_category_map():
    """Mapa slug -> ProductCategory, cacheado por requisição (evita N+1)."""
    from flask import g, has_request_context
    if has_request_context():
        cached = getattr(g, "_product_category_map", None)
        if cached is not None:
            return cached
    mapping = {c.slug: c for c in get_active_product_categories()}
    if has_request_context():
        try:
            g._product_category_map = mapping
        except Exception:
            pass
    return mapping


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    image_url = db.Column(db.String(200))
    # Categoria de exibição na Loja (filtros/chips). Ver PRODUCT_CATEGORIES.
    category = db.Column(db.String(40), index=True)
    mp_category_id = db.Column(db.String(50), default="others")
    ncm = db.Column(db.String(10))
    cfop = db.Column(db.String(10))
    cst = db.Column(db.String(5))
    csosn = db.Column(db.String(5))
    origem = db.Column(db.String(2))
    unidade = db.Column(db.String(10))
    aliquota_icms = db.Column(db.Numeric(10, 4))
    aliquota_pis = db.Column(db.Numeric(10, 4))
    aliquota_cofins = db.Column(db.Numeric(10, 4))

    # Campos de venda por clínica
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id', ondelete='SET NULL'), nullable=True, index=True)
    clinic_inventory_item_id = db.Column(db.Integer, db.ForeignKey('clinic_inventory_item.id', ondelete='SET NULL'), nullable=True)
    # Vendedor alternativo: casa de ração parceira
    casa_de_racao_id = db.Column(db.Integer, db.ForeignKey('casa_de_racao.id', ondelete='SET NULL'), nullable=True, index=True)
    # 'active' = visível na loja, 'inactive' = oculto pelo dono, 'pending' = aguardando aprovação
    status = db.Column(db.String(20), default='active', nullable=False)

    clinica = db.relationship('Clinica', backref=db.backref('produtos_loja', lazy='dynamic'))
    inventory_item = db.relationship('ClinicInventoryItem', backref=db.backref('produto_loja', uselist=False))
    casa_de_racao = db.relationship('CasaDeRacao', backref=db.backref('produtos_loja', lazy='dynamic'))

    # Items de pedido associados ao produto. O cascade facilita remover os
    # OrderItem relacionados quando o produto é excluído.
    order_items = db.relationship(
        "OrderItem",
        back_populates="product",
        cascade="all, delete-orphan"
    )

    @property
    def category_label(self):
        """Rótulo de exibição da categoria (ex.: 'racao' -> 'Ração')."""
        if not self.category:
            return None
        cat = product_category_map().get(self.category)
        return cat.label if cat else None

    @property
    def category_icon(self):
        """Ícone Font Awesome da categoria, com fallback genérico."""
        cat = product_category_map().get(self.category) if self.category else None
        return cat.icon if cat else "fa-tag"

    def __repr__(self):
        return f"{self.name} (R$ {self.price})"

    def __str__(self):
        return self.__repr__()


class ProductPhoto(db.Model):
    """Fotos adicionais para produtos."""
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    image_url = db.Column(db.String(200))

    product = db.relationship('Product', backref='extra_photos')






class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    shipping_address = db.Column(db.String(200))

    user = db.relationship(
        'User',
        backref=db.backref('orders', cascade='all, delete-orphan')
    )
    items = db.relationship('OrderItem', backref='order', cascade='all, delete-orphan')




    def total_value(self):
        """Calcula o valor total do pedido com base nos produtos e quantidades."""
        total = 0.0
        for item in self.items:
            if item.product:
                total += (item.product.price or 0) * item.quantity
        return total

    def __str__(self):
        nome_usuario = self.user.name if self.user else "Usuário desconhecido"
        valor = self.total_value()
        return f"Pedido #{self.id} de {nome_usuario} - R$ {valor:.2f}"

class OrderItem(db.Model):
    __tablename__ = "order_item"

    id          = db.Column(db.Integer, primary_key=True)
    order_id    = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    product_id  = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    # back_populates permite acesso recíproco a partir de Product.order_items
    product     = db.relationship("Product", back_populates="order_items")

    item_name   = db.Column(db.String(100), nullable=False)
    quantity    = db.Column(db.Integer, nullable=False, default=1)
    unit_price  = db.Column(db.Numeric(10, 2), nullable=True)   # NOVO 👈

    def __str__(self):
        return f"{self.product.name if self.product else self.item_name} x{self.quantity}"


class SavedAddress(db.Model):
    """Endereços extras salvos pelo usuário."""
    __tablename__ = 'saved_address'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    address = db.Column(db.String(200), nullable=False)

    # Delete saved addresses when the owning user is removed
    user = db.relationship(
        'User',
        backref=db.backref('saved_addresses', cascade='all, delete-orphan')
    )

    def __repr__(self):
        return self.address


class DeliveryRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    requested_by_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    requested_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    status = db.Column(db.String(20), default='pendente')
    worker_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
    )
    worker_latitude = db.Column(db.Float, nullable=True)
    worker_longitude = db.Column(db.Float, nullable=True)
    accepted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    canceled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    canceled_by_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
    )
    archived = db.Column(db.Boolean, default=False, nullable=False)
    # Vendedor responsável por esta entrega (apenas um dos dois estará preenchido)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id', ondelete='SET NULL'), nullable=True, index=True)
    casa_de_racao_id = db.Column(db.Integer, db.ForeignKey('casa_de_racao.id', ondelete='SET NULL'), nullable=True, index=True)
    # 'plataforma' = fila de entregadores, 'propria' = vendedor gerencia
    tipo_entrega = db.Column(db.String(20), default='plataforma', nullable=False)

    order = db.relationship('Order', backref='delivery_requests')
    requested_by = db.relationship(
        'User',
        foreign_keys=[requested_by_id],
        backref=db.backref('delivery_requests_made', cascade='all, delete-orphan'),
    )
    worker = db.relationship('User', foreign_keys=[worker_id])
    canceled_by = db.relationship('User', foreign_keys=[canceled_by_id])
    pickup_id   = db.Column(db.Integer, db.ForeignKey('pickup_location.id'))
    pickup      = db.relationship('PickupLocation')
    clinica     = db.relationship('Clinica', foreign_keys=[clinica_id])
    casa_de_racao = db.relationship('CasaDeRacao', foreign_keys=[casa_de_racao_id],
                                    backref=db.backref('delivery_requests', lazy='dynamic'))

    def __str__(self):
        return f"Entrega #{self.id} - Pedido #{self.order_id} ({self.status})"



class PickupLocation(db.Model):
    __tablename__ = "pickup_location"
    id          = db.Column(db.Integer, primary_key=True)
    nome        = db.Column(db.String(120))           # “Galpão Central”, “Hub Ribeirão”…
    endereco_id = db.Column(db.Integer, db.ForeignKey('endereco.id'))
    endereco    = db.relationship('Endereco')
    ativo       = db.Column(db.Boolean, default=True) # permite desativar pontos


    endereco    = db.relationship(
        "Endereco",
        back_populates="pickup_location",
        uselist=False
    )



class PaymentMethod(Enum):
    PIX = 'PIX'
    CREDIT_CARD = 'Cartão de Crédito'
    DEBIT_CARD = 'Cartão de Débito'
    BOLETO = 'Boleto'

class PaymentStatus(Enum):
    PENDING = 'Pendente'
    COMPLETED = 'Concluído'
    FAILED = 'Falhou'

class Payment(db.Model):
    __tablename__  = "payment"
    __table_args__ = (
        db.UniqueConstraint("transaction_id",  name="uq_payment_tx"),
        db.UniqueConstraint("external_reference", name="uq_payment_extref"),
    )

    id       = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=True)

    # ✅ fica só esta definição
    order = db.relationship(
        "Order",
        backref=db.backref("payment", uselist=False, cascade="all, delete-orphan"),
        uselist=False,
    )

    method = db.Column(
        PgEnum(PaymentMethod, name="paymentmethod", create_type=False),
        nullable=False,
    )
    status = db.Column(
        PgEnum(PaymentStatus, name="paymentstatus", create_type=False),
        default=PaymentStatus.PENDING,
        index=True,
    )

    transaction_id     = db.Column(db.String(255))
    external_reference = db.Column(db.String(255))
    mercado_pago_id    = db.Column(db.String(64))

    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    user    = db.relationship(
        "User",
        backref=db.backref("payments", cascade="all, delete-orphan"),
    )

    init_point = db.Column(db.String)

    # NOVO: valor congelado do pagamento
    amount = db.Column(db.Numeric(10, 2), nullable=True)  # Adicione este campo


# -------------------------- Planos de Saúde ---------------------------

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






















#testing sandbox
class PendingWebhook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mp_id = db.Column(db.BigInteger, unique=True)
    attempts = db.Column(db.Integer, default=0)
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


def _normalize_person_name(value):
    if value is None:
        return None

    normalized = " ".join(str(value).split())
    if not normalized:
        return normalized

    lowered = normalized.lower()
    result = []
    capitalize_next = True

    for char in lowered:
        if capitalize_next and char.isalpha():
            result.append(char.upper())
            capitalize_next = False
        else:
            result.append(char)
            capitalize_next = char in {" ", "-", "'"}

    return "".join(result)


def _normalize_model_name(target):
    if hasattr(target, "name"):
        target.name = _normalize_person_name(target.name)


@event.listens_for(User, "before_insert")
def _normalize_user_name_before_insert(mapper, connection, target):
    _normalize_model_name(target)


@event.listens_for(User, "before_update")
def _normalize_user_name_before_update(mapper, connection, target):
    _normalize_model_name(target)


@event.listens_for(Animal, "before_insert")
def _normalize_animal_name_before_insert(mapper, connection, target):
    _normalize_model_name(target)


@event.listens_for(Animal, "before_update")
def _normalize_animal_name_before_update(mapper, connection, target):
    _normalize_model_name(target)


# ──────────────────── Serviço de Vacinas Pagas ────────────────────

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
