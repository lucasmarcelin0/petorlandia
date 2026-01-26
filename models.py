try:
    from extensions import db
except ImportError:
    from .extensions import db

from flask_login import UserMixin
from flask import url_for, request, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta, timezone
from dateutil.relativedelta import relativedelta
from decimal import Decimal
import unicodedata
import enum
import uuid
from sqlalchemy import Enum, event, func, case
from enum import Enum
from sqlalchemy import Enum as PgEnum
from sqlalchemy.orm import synonym, object_session, deferred
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.exc import OperationalError, ProgrammingError
from time_utils import utcnow, now_in_brazil




class Endereco(db.Model):
    __tablename__ = 'endereco'
    id = db.Column(db.Integer, primary_key=True)
    cep = db.Column(db.String(9), nullable=False)  # Ex: 14620-000
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
    adotante = 'adotante'
    doador = 'doador'
    veterinario = 'veterinario'
    admin = 'admin'


# Usuário
class User(UserMixin, db.Model):
    __table_args__ = {'extend_existing': True}  # <- isso permite redefinir sem erro

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default='adotante', nullable=True)



    phone = db.Column(db.String(20))

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
    sent_messages = db.relationship(
        'Message',
        foreign_keys='Message.sender_id',
        back_populates='sender',
        cascade='all, delete-orphan',
        lazy='selectin',
    )
    received_messages = db.relationship(
        'Message',
        foreign_keys='Message.receiver_id',
        back_populates='receiver',
        cascade='all, delete-orphan',
        lazy='selectin',
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
    species = db.Column(db.String(50))
    breed = db.Column(db.String(100))
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
    nfse_username = deferred(db.Column(db.String(120)))
    nfse_password = deferred(db.Column(db.String(120)))
    nfse_cert_path = deferred(db.Column(db.String(200)))
    nfse_cert_password = deferred(db.Column(db.String(120)))
    nfse_token = deferred(db.Column(db.String(200)))

    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    owner = db.relationship('User', backref=db.backref('clinicas', foreign_keys='Clinica.owner_id'), foreign_keys=[owner_id])

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

    clinica = db.relationship('Clinica', backref='horarios')


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

    clinic = db.relationship('Clinica', backref='staff_members')
    user = db.relationship(
        'User',
        backref=db.backref('clinic_roles', cascade='all, delete-orphan'),
        passive_deletes=True,
    )


class NfseIssue(db.Model):
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
    xml = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    clinica = db.relationship('Clinica', backref=db.backref('nfse_xmls', cascade='all, delete-orphan'))
    nfse_issue = db.relationship('NfseIssue', back_populates='xmls')

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
class ClinicInventoryItem(db.Model):
    __tablename__ = 'clinic_inventory_item'
    id = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
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


class ClinicInventoryMovement(db.Model):
    __tablename__ = 'clinic_inventory_movement'

    id = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('clinic_inventory_item.id', ondelete='CASCADE'), nullable=False)
    quantity_change = db.Column(db.Integer, nullable=False)
    quantity_before = db.Column(db.Integer, nullable=False)
    quantity_after = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    clinica = db.relationship('Clinica', backref='inventory_movements')
    item = db.relationship('ClinicInventoryItem', back_populates='movements')


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
        backref=db.backref('classified_transactions', cascade='all, delete-orphan', lazy=True),
    )

    def __repr__(self):
        return f"<{self.origin} {self.category} R$ {self.value}>"


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
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'))

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
        if target.veterinario_id:
            vet = Veterinario.query.get(target.veterinario_id)
            if vet and vet.clinica_id:
                target.clinica_id = vet.clinica_id
        if not target.clinica_id and target.animal_id:
            animal = Animal.query.get(target.animal_id)
            if animal and animal.clinica_id:
                target.clinica_id = animal.clinica_id


event.listen(Appointment, 'before_insert', Appointment._validate_subscription)
event.listen(Appointment, 'before_update', Appointment._validate_subscription)
event.listen(Appointment, 'before_insert', Appointment._set_clinica)
event.listen(Appointment, 'before_update', Appointment._set_clinica)


def _create_veterinarian_membership(mapper, connection, target):
    """Ensure every veterinarian profile starts with a membership record."""

    trial_days = current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30)
    session = object_session(target) or db.session

    membership = getattr(target, 'membership', None)
    if membership is None:
        membership = VeterinarianMembership(
            veterinario_id=target.id,
            started_at=utcnow(),
            trial_ends_at=utcnow() + timedelta(days=trial_days),
        )
        session.add(membership)
    else:
        membership.ensure_trial_dates(trial_days)


event.listen(Veterinario, 'after_insert', _create_veterinarian_membership, propagate=True)

# Agendamento de exames
class ExamAppointment(db.Model):
    __tablename__ = 'exam_appointment'

    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    specialist_id = db.Column(db.Integer, db.ForeignKey('veterinario.id'), nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
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
        if not self.confirm_by:
            self.confirm_by = (self.request_time or utcnow()) + timedelta(hours=2)

    @property
    def status_display(self):
        if self.status == 'confirmed':
            return 'Aceito'
        if self.status == 'canceled':
            return 'Cancelado'
        if self.confirm_by and utcnow() > self.confirm_by:
            return 'Prazo expirado'
        return 'Aguardando aceitação'

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

    created_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )

    apresentacoes = db.relationship('ApresentacaoMedicamento', backref='medicamento', cascade='all, delete-orphan')

    def __str__(self):
        return self.nome

class ApresentacaoMedicamento(db.Model):
    __tablename__ = 'apresentacao_medicamento'
    id = db.Column(db.Integer, primary_key=True)
    medicamento_id = db.Column(db.Integer, db.ForeignKey('medicamento.id'), nullable=False)

    forma = db.Column(db.String(50), nullable=False)          # cápsula, líquido, etc.
    concentracao = db.Column(db.String(100), nullable=False)  # Ex: 50 mg/mL, 500 mg/cápsula

    def __str__(self):
        return f"{self.medicamento.nome} – {self.forma} ({self.concentracao})"


class ExameModelo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)  # ex: Hemograma, Raio-X...
    justificativa = db.Column(db.Text)
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


class VacinaModelo(db.Model):
    __tablename__ = 'vacina_modelo'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(50))  # Opcional, mas útil para o frontend
    fabricante = db.Column(db.String(100))
    doses_totais = db.Column(db.Integer)
    intervalo_dias = db.Column(db.Integer)
    frequencia = db.Column(db.String(50))
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


class TipoRacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marca = db.Column(db.String(100), nullable=False)
    linha = db.Column(db.String(100))  # Ex: "Premium Filhotes", "Golden Fórmula"
    recomendacao = db.Column(db.Float)  # g/kg/dia
    observacoes = db.Column(db.Text)
    peso_pacote_kg = db.Column(db.Float, default=15.0)  # Peso do pacote (kg)
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
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    image_url = db.Column(db.String(200))
    mp_category_id = db.Column(db.String(50), default="others")

    # Items de pedido associados ao produto. O cascade facilita remover os
    # OrderItem relacionados quando o produto é excluído.
    order_items = db.relationship(
        "OrderItem",
        back_populates="product",
        cascade="all, delete-orphan"
    )

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
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
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
