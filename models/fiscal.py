"""Modelos fiscais (emissão NF-e/NFS-e)."""

import enum

try:
    from extensions import db
except ImportError:  # pragma: no cover - fallback for package import
    from .extensions import db

from time_utils import now_in_brazil
from sqlalchemy import Enum as PgEnum


class FiscalDocumentStatus(enum.Enum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    SENDING = "SENDING"
    PROCESSING = "PROCESSING"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class FiscalDocumentType(enum.Enum):
    NFSE = "NFSE"
    NFE = "NFE"


class FiscalEmitter(db.Model):
    __tablename__ = "fiscal_emitters"
    __table_args__ = (
        db.UniqueConstraint("clinic_id", name="uq_fiscal_emitters_clinic_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinica.id"), nullable=False, index=True)
    cnpj = db.Column(db.String(18), nullable=False)
    razao_social = db.Column(db.String(200), nullable=False)
    nome_fantasia = db.Column(db.String(200))
    inscricao_municipal = db.Column(db.String(60))
    inscricao_estadual = db.Column(db.String(60))
    municipio_ibge = db.Column(db.String(10))
    uf = db.Column(db.String(2))
    endereco_json = db.Column(db.JSON)
    regime_tributario = db.Column(db.String(60))
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=now_in_brazil,
        onupdate=now_in_brazil,
    )

    clinic = db.relationship("Clinica", backref=db.backref("fiscal_emitter", uselist=False))
    certificates = db.relationship(
        "FiscalCertificate",
        back_populates="emitter",
        cascade="all, delete-orphan",
    )
    documents = db.relationship(
        "FiscalDocument",
        back_populates="emitter",
        cascade="all, delete-orphan",
    )
    counters = db.relationship(
        "FiscalCounter",
        back_populates="emitter",
        cascade="all, delete-orphan",
    )


class FiscalCertificate(db.Model):
    __tablename__ = "fiscal_certificates"

    id = db.Column(db.Integer, primary_key=True)
    emitter_id = db.Column(db.Integer, db.ForeignKey("fiscal_emitters.id"), nullable=False, index=True)
    pfx_encrypted = db.Column(db.LargeBinary, nullable=False)
    pfx_password_encrypted = db.Column(db.Text, nullable=False)
    fingerprint_sha256 = db.Column(db.String(64), nullable=False)
    valid_from = db.Column(db.DateTime(timezone=True))
    valid_to = db.Column(db.DateTime(timezone=True))
    subject_cnpj = db.Column(db.String(14))
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=now_in_brazil,
        onupdate=now_in_brazil,
    )

    emitter = db.relationship("FiscalEmitter", back_populates="certificates")


class FiscalDocument(db.Model):
    __tablename__ = "fiscal_documents"

    id = db.Column(db.Integer, primary_key=True)
    emitter_id = db.Column(
        db.Integer,
        db.ForeignKey("fiscal_emitters.id"),
        nullable=False,
        index=True,
    )
    clinic_id = db.Column(
        db.Integer,
        db.ForeignKey("clinica.id"),
        nullable=False,
        index=True,
    )
    doc_type = db.Column(
        PgEnum(FiscalDocumentType, name="fiscal_document_type", create_type=False),
        nullable=False,
    )
    status = db.Column(
        PgEnum(FiscalDocumentStatus, name="fiscal_document_status", create_type=False),
        nullable=False,
        default=FiscalDocumentStatus.DRAFT,
    )
    series = db.Column(db.String(20))
    number = db.Column(db.Integer)
    access_key = db.Column(db.String(60))
    nfse_number = db.Column(db.String(60))
    protocol = db.Column(db.String(80))
    verification_code = db.Column(db.String(80))
    payload_json = db.Column(db.JSON)
    xml_signed = db.Column(db.Text)
    xml_authorized = db.Column(db.Text)
    pdf_path = db.Column(db.String(255))
    error_code = db.Column(db.String(50))
    error_message = db.Column(db.Text)
    related_type = db.Column(db.String(40))
    related_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=now_in_brazil,
        onupdate=now_in_brazil,
    )
    authorized_at = db.Column(db.DateTime(timezone=True))
    canceled_at = db.Column(db.DateTime(timezone=True))

    emitter = db.relationship("FiscalEmitter", back_populates="documents")
    clinic = db.relationship("Clinica", backref=db.backref("fiscal_documents", cascade="all, delete-orphan"))
    events = db.relationship(
        "FiscalEvent",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class FiscalEvent(db.Model):
    __tablename__ = "fiscal_events"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("fiscal_documents.id"), nullable=False, index=True)
    event_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(40))
    request_xml = db.Column(db.Text)
    response_xml = db.Column(db.Text)
    protocol = db.Column(db.String(80))
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    document = db.relationship("FiscalDocument", back_populates="events")


class FiscalCounter(db.Model):
    __tablename__ = "fiscal_counters"
    __table_args__ = (
        db.UniqueConstraint("emitter_id", "doc_type", "series", name="uq_fiscal_counters_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    emitter_id = db.Column(db.Integer, db.ForeignKey("fiscal_emitters.id"), nullable=False, index=True)
    doc_type = db.Column(
        PgEnum(FiscalDocumentType, name="fiscal_document_type", create_type=False),
        nullable=False,
    )
    series = db.Column(db.String(20), nullable=False, default="1")
    current_number = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=now_in_brazil,
        onupdate=now_in_brazil,
    )

    emitter = db.relationship("FiscalEmitter", back_populates="counters")
