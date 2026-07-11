"""Financeiro e fiscal: NFS-e, snapshots, contas e transações classificadas.

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


from .clinica import _encrypt_nfse_value, _decrypt_nfse_value


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

