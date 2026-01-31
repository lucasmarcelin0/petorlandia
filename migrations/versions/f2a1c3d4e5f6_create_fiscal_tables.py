"""create fiscal tables"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2a1c3d4e5f6"
down_revision = "1f3f1a5e660d"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    fiscal_document_type = sa.Enum(
        "NFSE",
        "NFE",
        name="fiscal_document_type",
        create_type=False,
    )
    fiscal_document_status = sa.Enum(
        "DRAFT",
        "QUEUED",
        "SENDING",
        "PROCESSING",
        "AUTHORIZED",
        "REJECTED",
        "FAILED",
        "CANCELED",
        name="fiscal_document_status",
        create_type=False,
    )
    fiscal_document_type.create(bind, checkfirst=True)
    fiscal_document_status.create(bind, checkfirst=True)

    if "fiscal_emitters" not in inspector.get_table_names():
        op.create_table(
            "fiscal_emitters",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinica.id"), nullable=False),
            sa.Column("cnpj", sa.String(length=18), nullable=False),
            sa.Column("razao_social", sa.String(length=200), nullable=False),
            sa.Column("nome_fantasia", sa.String(length=200), nullable=True),
            sa.Column("inscricao_municipal", sa.String(length=60), nullable=True),
            sa.Column("inscricao_estadual", sa.String(length=60), nullable=True),
            sa.Column("municipio_ibge", sa.String(length=10), nullable=True),
            sa.Column("uf", sa.String(length=2), nullable=True),
            sa.Column("endereco_json", sa.JSON(), nullable=True),
            sa.Column("regime_tributario", sa.String(length=60), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("clinic_id", name="uq_fiscal_emitters_clinic_id"),
        )
        op.create_index("ix_fiscal_emitters_clinic_id", "fiscal_emitters", ["clinic_id"])

    if "fiscal_certificates" not in inspector.get_table_names():
        op.create_table(
            "fiscal_certificates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("emitter_id", sa.Integer(), sa.ForeignKey("fiscal_emitters.id"), nullable=False),
            sa.Column("pfx_encrypted", sa.LargeBinary(), nullable=False),
            sa.Column("pfx_password_encrypted", sa.Text(), nullable=False),
            sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
            sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
            sa.Column("subject_cnpj", sa.String(length=14), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_fiscal_certificates_emitter_id", "fiscal_certificates", ["emitter_id"])

    if "fiscal_documents" not in inspector.get_table_names():
        op.create_table(
            "fiscal_documents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("emitter_id", sa.Integer(), sa.ForeignKey("fiscal_emitters.id"), nullable=False),
            sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinica.id"), nullable=False),
            sa.Column("doc_type", fiscal_document_type, nullable=False),
            sa.Column("status", fiscal_document_status, nullable=False),
            sa.Column("series", sa.String(length=20), nullable=True),
            sa.Column("number", sa.Integer(), nullable=True),
            sa.Column("access_key", sa.String(length=60), nullable=True),
            sa.Column("nfse_number", sa.String(length=60), nullable=True),
            sa.Column("protocol", sa.String(length=80), nullable=True),
            sa.Column("verification_code", sa.String(length=80), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("xml_signed", sa.Text(), nullable=True),
            sa.Column("xml_authorized", sa.Text(), nullable=True),
            sa.Column("pdf_path", sa.String(length=255), nullable=True),
            sa.Column("error_code", sa.String(length=50), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("related_type", sa.String(length=40), nullable=True),
            sa.Column("related_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_fiscal_documents_emitter_id", "fiscal_documents", ["emitter_id"])
        op.create_index("ix_fiscal_documents_clinic_id", "fiscal_documents", ["clinic_id"])

    if "fiscal_events" not in inspector.get_table_names():
        op.create_table(
            "fiscal_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("document_id", sa.Integer(), sa.ForeignKey("fiscal_documents.id"), nullable=False),
            sa.Column("event_type", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=True),
            sa.Column("request_xml", sa.Text(), nullable=True),
            sa.Column("response_xml", sa.Text(), nullable=True),
            sa.Column("protocol", sa.String(length=80), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_fiscal_events_document_id", "fiscal_events", ["document_id"])

    if "fiscal_counters" not in inspector.get_table_names():
        op.create_table(
            "fiscal_counters",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("emitter_id", sa.Integer(), sa.ForeignKey("fiscal_emitters.id"), nullable=False),
            sa.Column("doc_type", fiscal_document_type, nullable=False),
            sa.Column("series", sa.String(length=20), nullable=False),
            sa.Column("current_number", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("emitter_id", "doc_type", "series", name="uq_fiscal_counters_key"),
        )
        op.create_index("ix_fiscal_counters_emitter_id", "fiscal_counters", ["emitter_id"])


def downgrade():
    op.drop_index("ix_fiscal_counters_emitter_id", table_name="fiscal_counters")
    op.drop_table("fiscal_counters")

    op.drop_index("ix_fiscal_events_document_id", table_name="fiscal_events")
    op.drop_table("fiscal_events")

    op.drop_index("ix_fiscal_documents_clinic_id", table_name="fiscal_documents")
    op.drop_index("ix_fiscal_documents_emitter_id", table_name="fiscal_documents")
    op.drop_table("fiscal_documents")

    op.drop_index("ix_fiscal_certificates_emitter_id", table_name="fiscal_certificates")
    op.drop_table("fiscal_certificates")

    op.drop_index("ix_fiscal_emitters_clinic_id", table_name="fiscal_emitters")
    op.drop_table("fiscal_emitters")

    bind = op.get_bind()
    sa.Enum(name="fiscal_document_status").drop(bind, checkfirst=True)
    sa.Enum(name="fiscal_document_type").drop(bind, checkfirst=True)
