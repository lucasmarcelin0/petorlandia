"""Consultas, prescrições, orçamentos, exames e protocolos clínicos.

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

    assinatura_arquivo_url = db.Column(db.String(500), nullable=True)
    assinatura_enviada_em = db.Column(db.DateTime(timezone=True), nullable=True)
    assinatura_enviada_por_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    assinatura_enviada_por = db.relationship('User', foreign_keys=[assinatura_enviada_por_id])

    @property
    def assinatura_enviada(self):
        return bool(self.assinatura_arquivo_url)


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


class TratamentoAcompanhamento(db.Model):
    """Acompanhamento de um bloco de prescrição: compras, administrações e fotos."""
    __tablename__ = 'tratamento_acompanhamento'

    id = db.Column(db.Integer, primary_key=True)
    bloco_id = db.Column(
        db.Integer,
        db.ForeignKey('bloco_prescricao.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
    )
    animal_id = db.Column(
        db.Integer,
        db.ForeignKey('animal.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    status = db.Column(db.String(20), nullable=False, default='ativo')  # ativo | concluido | interrompido
    data_inicio = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    criado_por_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    bloco = db.relationship(
        'BlocoPrescricao',
        backref=db.backref('acompanhamento', uselist=False, cascade='all, delete-orphan'),
    )
    animal = db.relationship('Animal', backref=db.backref('acompanhamentos_tratamento', lazy=True))
    criado_por = db.relationship('User', foreign_keys=[criado_por_id])
    itens = db.relationship(
        'ItemTratamento',
        backref='acompanhamento',
        cascade='all, delete-orphan',
        order_by='ItemTratamento.id',
    )
    fotos = db.relationship(
        'FotoTratamento',
        backref='acompanhamento',
        cascade='all, delete-orphan',
        order_by='FotoTratamento.enviada_em',
    )


class ItemTratamento(db.Model):
    """Um medicamento/shampoo/pomada da receita dentro do acompanhamento.

    modo 'agendado' = posologia interpretada, doses pré-geradas em AdministracaoRegistro.
    modo 'livre' = sem cadência confiável; tutor registra cada aplicação manualmente.
    """
    __tablename__ = 'item_tratamento'

    id = db.Column(db.Integer, primary_key=True)
    acompanhamento_id = db.Column(
        db.Integer,
        db.ForeignKey('tratamento_acompanhamento.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    prescricao_id = db.Column(
        db.Integer,
        db.ForeignKey('prescricao.id', ondelete='CASCADE'),
        nullable=False,
    )
    modo = db.Column(db.String(10), nullable=False, default='livre')  # agendado | livre
    intervalo_horas = db.Column(db.Integer)
    duracao_dias = db.Column(db.Integer)
    comprado_em = db.Column(db.DateTime(timezone=True))
    comprado_por_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    prescricao = db.relationship('Prescricao')
    comprado_por = db.relationship('User', foreign_keys=[comprado_por_id])
    registros = db.relationship(
        'AdministracaoRegistro',
        backref='item',
        cascade='all, delete-orphan',
        order_by='AdministracaoRegistro.prevista_para',
    )


class AdministracaoRegistro(db.Model):
    """Uma dose prevista (modo agendado) ou aplicação avulsa (modo livre)."""
    __tablename__ = 'administracao_registro'

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(
        db.Integer,
        db.ForeignKey('item_tratamento.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    prevista_para = db.Column(db.DateTime(timezone=True))  # null em aplicações avulsas
    realizada_em = db.Column(db.DateTime(timezone=True))
    realizada_por_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(10), nullable=False, default='pendente')  # pendente | feita | pulada
    observacao = db.Column(db.Text)

    realizada_por = db.relationship('User', foreign_keys=[realizada_por_id])


class FotoTratamento(db.Model):
    """Foto de evolução enviada pelo tutor (ou equipe) durante o tratamento."""
    __tablename__ = 'foto_tratamento'

    id = db.Column(db.Integer, primary_key=True)
    acompanhamento_id = db.Column(
        db.Integer,
        db.ForeignKey('tratamento_acompanhamento.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    url = db.Column(db.String(400), nullable=False)
    observacao = db.Column(db.Text)
    enviada_em = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    enviada_por_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    enviada_por = db.relationship('User', foreign_keys=[enviada_por_id])


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


class OrthancStudy(db.Model):
    """Estudo DICOM recebido do PACS Orthanc via webhook (ex.: ultrassom VINNO D2).

    Registro idempotente por StudyInstanceUID; quando o PatientName casa com um
    único Animal, um rascunho de ExameImagem é criado automaticamente.
    """
    __tablename__ = 'orthanc_study'

    id = db.Column(db.Integer, primary_key=True)
    study_instance_uid = db.Column(db.String(128), nullable=False, unique=True, index=True)
    orthanc_study_id = db.Column(db.String(64), nullable=True)
    accession_number = db.Column(db.String(64), nullable=True)
    study_description = db.Column(db.String(255), nullable=True)
    study_date = db.Column(db.Date, nullable=True)
    patient_name = db.Column(db.String(160), nullable=True)
    patient_dicom_id = db.Column(db.String(64), nullable=True)
    patient_sex = db.Column(db.String(16), nullable=True)
    series_count = db.Column(db.Integer, nullable=True)
    raw_payload = db.Column(db.Text, nullable=True)
    match_status = db.Column(db.String(20), nullable=False, default='unmatched', index=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id', ondelete='SET NULL'), nullable=True, index=True)
    exame_imagem_id = db.Column(db.Integer, db.ForeignKey('exame_imagem.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, onupdate=now_in_brazil, nullable=False)

    animal = db.relationship('Animal')
    exame_imagem = db.relationship('ExameImagem')


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

