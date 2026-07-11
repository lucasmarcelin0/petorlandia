"""Agenda: horários, agendamentos, plantões e eventos.

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
from .pacientes import Animal
from .usuarios import Veterinario
from security.crypto import (
    MissingMasterKeyError,
    decrypt_text,
    decrypt_text_for_clinic,
    encrypt_text,
    looks_encrypted_text,
)




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

