"""Modelos fiscais (emissão NF-e/NFS-e)."""

import enum

try:
    from extensions import db
except ImportError:  # pragma: no cover - fallback for package import
    from .extensions import db

from cryptography.fernet import InvalidToken
from time_utils import now_in_brazil
from sqlalchemy import Enum as PgEnum
from sqlalchemy.orm import synonym
from security.crypto import (
    MissingMasterKeyError,
    decrypt_text_for_clinic,
    encrypt_text_for_clinic,
    looks_encrypted_text,
)


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
    __table_args__ = (
        db.Index("ix_fiscal_documents_source", "clinic_id", "source_type", "source_id"),
        db.Index("ix_fiscal_documents_related", "clinic_id", "related_type", "related_id"),
    )

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
    # XMLs são mantidos criptografados no banco com chave derivada por clínica
    # (ver security.crypto). Eles contêm CPF/CNPJ do tomador, valores da nota
    # e a assinatura digital — qualquer dump de backup ou replica exposta
    # vazaria base fiscal inteira. Acesso sempre via property (get/set).
    _xml_signed = db.Column("xml_signed", db.Text)
    _xml_authorized = db.Column("xml_authorized", db.Text)
    pdf_path = db.Column(db.String(255))
    error_code = db.Column(db.String(50))
    error_message = db.Column(db.Text)
    source_type = db.Column(db.String(40))
    source_id = db.Column(db.Integer)
    related_type = db.Column(db.String(40))
    related_id = db.Column(db.Integer)
    human_reference = db.Column(db.String(255))
    animal_name = db.Column(db.String(120))
    tutor_name = db.Column(db.String(120))
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

    # ── XMLs criptografados ────────────────────────────────────────────────
    # Padrão: getter descriptografa se o blob começar com FERNET_PREFIX;
    # setter só cifra quando não reconhece um token já cifrado (idempotente,
    # seguro para re-salvamentos). InvalidToken cai para retornar o valor
    # bruto — backfill antigo pode ter blobs em plaintext que o backfill
    # script vai migrar depois. MissingMasterKeyError NÃO é engolida: sem
    # chave mestra, queremos barulho em produção, não silêncio.
    def _decrypt_xml(self, blob):
        if not blob:
            return blob
        try:
            return decrypt_text_for_clinic(self.clinic_id, blob)
        except InvalidToken:
            return blob
        except MissingMasterKeyError:
            raise

    def _encrypt_xml_for_set(self, value):
        if not value:
            return value
        # Já cifrado? não re-envelopa. Cuidado: decrypt_text_for_clinic
        # *silenciosamente* devolve plaintext se o blob não começar com
        # FERNET_PREFIX (não levanta InvalidToken). Por isso não dá para
        # usar try/except decrypt — a gente checa o prefixo explicitamente.
        if looks_encrypted_text(value):
            return value
        if not self.clinic_id:
            raise ValueError("clinic_id deve estar definido antes de armazenar XML fiscal.")
        return encrypt_text_for_clinic(self.clinic_id, value)

    def _get_xml_signed(self):
        return self._decrypt_xml(self._xml_signed)

    def _set_xml_signed(self, value):
        self._xml_signed = self._encrypt_xml_for_set(value)

    xml_signed = synonym(
        "_xml_signed",
        descriptor=property(_get_xml_signed, _set_xml_signed),
    )

    def _get_xml_authorized(self):
        return self._decrypt_xml(self._xml_authorized)

    def _set_xml_authorized(self, value):
        self._xml_authorized = self._encrypt_xml_for_set(value)

    xml_authorized = synonym(
        "_xml_authorized",
        descriptor=property(_get_xml_authorized, _set_xml_authorized),
    )

    @property
    def service_descriptions(self) -> list[str]:
        payload = self.payload_json or {}
        descriptions = [
            item.get("descricao")
            for item in (payload.get("itens") or [])
            if item.get("descricao")
        ]
        if not descriptions:
            servico = payload.get("servico") or {}
            if servico.get("descricao"):
                descriptions.append(servico["descricao"])
        if not descriptions and payload.get("descricao"):
            descriptions.append(payload["descricao"])
        return descriptions

    @property
    def total_amount(self):
        payload = self.payload_json or {}
        if payload.get("valor_total") is not None:
            return payload["valor_total"]
        servico = payload.get("servico") or {}
        if servico.get("valor") is not None:
            return servico["valor"]
        return None


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
