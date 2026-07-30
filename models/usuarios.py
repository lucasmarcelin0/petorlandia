"""Usuários, veterinários, memberships e compartilhamento de dados.

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
import math
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

    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=True)
    last_login = db.Column(db.DateTime(timezone=True), nullable=True)



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


HABILITACAO_CRMV = 'crmv'
HABILITACAO_ESTAGIARIO = 'estagiario'

HABILITACAO_CHOICES = [
    (HABILITACAO_CRMV, 'Veterinário(a) com CRMV'),
    (HABILITACAO_ESTAGIARIO, 'Estagiário(a) sob supervisão'),
]

HABILITACAO_LABELS = dict(HABILITACAO_CHOICES)


class AssinaturaProfissional:
    """Como um profissional deve ser identificado num documento que sai da clínica.

    Existe para que nenhum template monte a atribuição legal por conta própria:
    estagiário nunca tem CRMV, então quem responde pelo documento é o
    supervisor. Ver `Veterinario.assinatura`.
    """

    __slots__ = ('nome', 'crmv', 'crmv_estado', 'papel', 'supervisor_nome',
                 'supervisor_crmv', 'supervisor_crmv_estado', 'pode_assinar')

    def __init__(self, *, nome, crmv=None, crmv_estado=None, papel=None,
                 supervisor_nome=None, supervisor_crmv=None,
                 supervisor_crmv_estado=None, pode_assinar=False):
        self.nome = nome
        self.crmv = crmv
        self.crmv_estado = crmv_estado
        self.papel = papel
        self.supervisor_nome = supervisor_nome
        self.supervisor_crmv = supervisor_crmv
        self.supervisor_crmv_estado = supervisor_crmv_estado
        self.pode_assinar = pode_assinar

    @property
    def crmv_formatado(self):
        """CRMV legalmente responsável pelo documento, ou None."""
        numero = self.crmv or self.supervisor_crmv
        estado = self.crmv_estado if self.crmv else self.supervisor_crmv_estado
        if not numero:
            return None
        return f"CRMV {numero}/{estado}" if estado else f"CRMV {numero}"

    @property
    def responsavel_tecnico(self):
        """Nome de quem responde tecnicamente (supervisor, no caso do estagiário)."""
        return self.supervisor_nome or self.nome

    @property
    def linha_completa(self):
        """Atribuição pronta para impressão."""
        partes = [self.nome]
        if self.papel:
            partes.append(self.papel)
        if self.supervisor_nome:
            supervisao = f"sob supervisão de {self.supervisor_nome}"
            if self.supervisor_crmv:
                sup_estado = self.supervisor_crmv_estado
                sufixo = f"{self.supervisor_crmv}/{sup_estado}" if sup_estado else self.supervisor_crmv
                supervisao += f" (CRMV {sufixo})"
            partes.append(supervisao)
        elif self.crmv_formatado:
            partes.append(self.crmv_formatado)
        return ' · '.join(partes)

    def __str__(self):
        return self.linha_completa


class Veterinario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    # Estagiário não tem CRMV: a coluna é nullable e a habilitação diz se a
    # pessoa pode assinar ato veterinário. Ver `pode_assinar` / `assinatura`.
    crmv = db.Column(db.String(20), nullable=True)
    crmv_estado = db.Column(db.String(2), nullable=True)
    habilitacao = db.Column(db.String(20), nullable=False, default=HABILITACAO_CRMV)
    supervisor_id = db.Column(
        db.Integer,
        db.ForeignKey('veterinario.id', ondelete='SET NULL'),
        nullable=True,
    )
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'))
    public_profile_type = db.Column(db.String(20), nullable=False, default='profissional')
    # Publicação é uma decisão explícita do administrador. Um cadastro novo
    # nunca deve virar prova pública apenas por ter preenchido um CRMV.
    public_visible = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship('User', back_populates='veterinario', uselist=False)
    supervisor = db.relationship(
        'Veterinario',
        remote_side=[id],
        backref='supervisionados',
        foreign_keys=[supervisor_id],
    )
    specialties = db.relationship('Specialty', secondary='veterinario_especialidade', backref='veterinarios')
    clinicas = db.relationship(
        'Clinica',
        secondary='veterinario_clinica',
        back_populates='veterinarios_associados',
    )
    cidades_atendidas = db.relationship(
        'VeterinarioAtendeCidade',
        backref='veterinario',
        cascade='all, delete-orphan',
        lazy='selectin',
    )

    @property
    def specialty_list(self):
        return ", ".join(s.nome for s in self.specialties)

    @property
    def is_estagiario(self):
        return (self.habilitacao or HABILITACAO_CRMV) == HABILITACAO_ESTAGIARIO

    @property
    def pode_assinar(self):
        """True apenas para quem tem CRMV próprio.

        Estagiário jamais assina: quem responde pelo documento é o supervisor.
        """
        return not self.is_estagiario and bool(self.crmv)

    @property
    def crmv_exibicao(self):
        """CRMV para exibir na interface, ou None quando não existe.

        Nunca inventa número: estagiário devolve None e a UI mostra o papel.
        """
        if self.is_estagiario or not self.crmv:
            return None
        return f"{self.crmv}/{self.crmv_estado}" if self.crmv_estado else self.crmv

    @property
    def habilitacao_label(self):
        return HABILITACAO_LABELS.get(
            self.habilitacao or HABILITACAO_CRMV, 'Veterinário(a) com CRMV'
        )

    @property
    def assinatura(self):
        """Atribuição legal deste profissional — ver `AssinaturaProfissional`."""
        nome = getattr(self.user, 'name', None) or f'Profissional #{self.id}'
        if not self.is_estagiario:
            return AssinaturaProfissional(
                nome=nome,
                crmv=self.crmv,
                crmv_estado=self.crmv_estado,
                pode_assinar=bool(self.crmv),
            )
        supervisor = self.supervisor
        supervisor_nome = getattr(getattr(supervisor, 'user', None), 'name', None)
        # Supervisor precisa ele próprio ter CRMV para responder pelo documento.
        supervisor_apto = bool(supervisor and supervisor.pode_assinar)
        return AssinaturaProfissional(
            nome=nome,
            papel='Estagiário(a)',
            supervisor_nome=supervisor_nome if supervisor_apto else None,
            supervisor_crmv=supervisor.crmv if supervisor_apto else None,
            supervisor_crmv_estado=supervisor.crmv_estado if supervisor_apto else None,
            pode_assinar=False,
        )

    def __str__(self):
        identificacao = self.crmv_exibicao
        if identificacao:
            return f"{self.user.name} (CRMV: {identificacao})"
        return f"{self.user.name} ({self.habilitacao_label})"


class VeterinarioAtendeCidade(db.Model):
    """Cidade atendida por um veterinário volante (ex.: ultrassonografista).

    Permite que um profissional cubra várias cidades além da do seu endereço.
    Quando não há nenhuma linha, o filtro cai para a cidade do endereço (compat).
    """
    __tablename__ = 'veterinario_atende_cidade'
    __table_args__ = (
        db.UniqueConstraint('veterinario_id', 'cidade', name='uq_vet_atende_cidade'),
    )

    id = db.Column(db.Integer, primary_key=True)
    veterinario_id = db.Column(
        db.Integer,
        db.ForeignKey('veterinario.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    cidade = db.Column(db.String(120), nullable=False)
    uf = db.Column(db.String(2), nullable=True)

    def __str__(self):
        return f"{self.cidade}{'/' + self.uf if self.uf else ''}"


class ProfessionalService(db.Model):
    """Serviço publicado por um profissional, com preços por público-alvo."""

    __tablename__ = 'professional_service'

    id = db.Column(db.Integer, primary_key=True)
    veterinario_id = db.Column(
        db.Integer,
        db.ForeignKey('veterinario.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    service_type = db.Column(db.String(40), nullable=False, default='consulta')
    title = db.Column(db.String(140), nullable=False)
    description = db.Column(db.Text, nullable=True)
    audience = db.Column(db.String(20), nullable=False, default='tutor')
    mode = db.Column(db.String(40), nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    business_start = db.Column(db.Time, nullable=True)
    business_end = db.Column(db.Time, nullable=True)
    tutor_price = db.Column(db.Numeric(10, 2), nullable=True)
    clinic_business_price = db.Column(db.Numeric(10, 2), nullable=True)
    clinic_after_hours_price = db.Column(db.Numeric(10, 2), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    veterinario = db.relationship(
        'Veterinario',
        backref=db.backref('professional_services', cascade='all, delete-orphan', lazy='selectin'),
    )

    @property
    def is_for_tutors(self):
        return self.audience in {'tutor', 'both'}

    @property
    def is_for_clinics(self):
        return self.audience in {'clinic', 'both'}

    def __str__(self):
        return f"{self.title} ({self.service_type})"


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
    #: Assinatura (preapproval) criada no Mercado Pago. O ID pode existir ainda
    #: com autorização pendente; ``payment_method_set_at`` registra quando o
    #: provedor confirma que a renovação ficou ativa.
    preapproval_id = db.Column(db.String(64), nullable=True)
    payment_method_set_at = db.Column(db.DateTime(timezone=True), nullable=True)

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

    def has_payment_method(self) -> bool:
        """True quando o Mercado Pago confirmou a autorização da assinatura.

        Só ter ``preapproval_id`` não basta: esse ID também existe enquanto a
        pessoa ainda está na tela de autorização e pode abandonar o fluxo.
        """

        return bool(self.preapproval_id and self.payment_method_set_at)

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
        return max(math.ceil(delta.total_seconds() / 86400), 0)

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


def _create_veterinarian_membership(mapper, connection, target):
    """Ensure every veterinarian profile starts with a membership record."""

    # ``ensure_veterinarian_membership`` may already have associated a pending
    # ORM membership with this profile. During this ``after_insert`` hook that
    # pending row has not been written yet, so a database-only lookup cannot
    # see it and would create a duplicate row for the same veterinarian.
    if target.__dict__.get('membership') is not None:
        return

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


_NAME_PARTICLES = {"da", "de", "do", "das", "dos", "e", "di", "du"}


def _normalize_person_name(value):
    if value is None:
        return None

    normalized = " ".join(str(value).split())
    if not normalized:
        return normalized

    words = []
    for index, word in enumerate(normalized.lower().split(" ")):
        if index > 0 and word in _NAME_PARTICLES:
            words.append(word)
            continue
        chars = []
        capitalize_next = True
        for char in word:
            if capitalize_next and char.isalpha():
                chars.append(char.upper())
                capitalize_next = False
            else:
                chars.append(char)
                capitalize_next = char in {"-", "'"}
        words.append("".join(chars))

    return " ".join(words)


def _normalize_model_name(target):
    if hasattr(target, "name"):
        target.name = _normalize_person_name(target.name)


@event.listens_for(User, "before_insert")
def _normalize_user_name_before_insert(mapper, connection, target):
    _normalize_model_name(target)


@event.listens_for(User, "before_update")
def _normalize_user_name_before_update(mapper, connection, target):
    _normalize_model_name(target)
