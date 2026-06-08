"""add exame imagem flow

Revision ID: 0b6d9e3f4a12
Revises: fb8c2d1e4a6f
Create Date: 2026-06-08 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0b6d9e3f4a12"
down_revision = "fb8c2d1e4a6f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "exame_imagem",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("animal_id", sa.Integer(), nullable=False),
        sa.Column("tutor_id", sa.Integer(), nullable=False),
        sa.Column("clinica_requisitante_id", sa.Integer(), nullable=True),
        sa.Column("profissional_id", sa.Integer(), nullable=True),
        sa.Column("documento_id", sa.Integer(), nullable=True),
        sa.Column("exame_solicitado_id", sa.Integer(), nullable=True),
        sa.Column("tipo_exame", sa.String(length=160), nullable=False),
        sa.Column("data_exame", sa.Date(), nullable=True),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("impressao_diagnostica", sa.Text(), nullable=True),
        sa.Column("profissional_nome", sa.String(length=160), nullable=True),
        sa.Column("profissional_crmv", sa.String(length=60), nullable=True),
        sa.Column("arquivo_pdf_url", sa.String(length=500), nullable=True),
        sa.Column("arquivo_pdf_filename", sa.String(length=255), nullable=True),
        sa.Column("arquivo_pdf_content_type", sa.String(length=120), nullable=True),
        sa.Column("arquivo_pdf_size", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("liberado_para_clinica", sa.Boolean(), nullable=False),
        sa.Column("liberado_para_tutor", sa.Boolean(), nullable=False),
        sa.Column("data_liberacao_clinica", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_liberacao_tutor", sa.DateTime(timezone=True), nullable=True),
        sa.Column("usuario_que_liberou_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["animal_id"], ["animal.id"]),
        sa.ForeignKeyConstraint(["clinica_requisitante_id"], ["clinica.id"]),
        sa.ForeignKeyConstraint(["documento_id"], ["animal_documento.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["exame_solicitado_id"], ["exame_solicitado.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["profissional_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tutor_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["usuario_que_liberou_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_exame_imagem_animal_id"), "exame_imagem", ["animal_id"], unique=False)
    op.create_index(op.f("ix_exame_imagem_clinica_requisitante_id"), "exame_imagem", ["clinica_requisitante_id"], unique=False)
    op.create_index(op.f("ix_exame_imagem_profissional_id"), "exame_imagem", ["profissional_id"], unique=False)
    op.create_index(op.f("ix_exame_imagem_status"), "exame_imagem", ["status"], unique=False)
    op.create_index(op.f("ix_exame_imagem_tutor_id"), "exame_imagem", ["tutor_id"], unique=False)

    op.create_table(
        "exame_imagem_pdf_access_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exame_imagem_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["exame_imagem_id"], ["exame_imagem.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_exame_imagem_pdf_access_log_exame_imagem_id"), "exame_imagem_pdf_access_log", ["exame_imagem_id"], unique=False)
    op.create_index(op.f("ix_exame_imagem_pdf_access_log_user_id"), "exame_imagem_pdf_access_log", ["user_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_exame_imagem_pdf_access_log_user_id"), table_name="exame_imagem_pdf_access_log")
    op.drop_index(op.f("ix_exame_imagem_pdf_access_log_exame_imagem_id"), table_name="exame_imagem_pdf_access_log")
    op.drop_table("exame_imagem_pdf_access_log")
    op.drop_index(op.f("ix_exame_imagem_tutor_id"), table_name="exame_imagem")
    op.drop_index(op.f("ix_exame_imagem_status"), table_name="exame_imagem")
    op.drop_index(op.f("ix_exame_imagem_profissional_id"), table_name="exame_imagem")
    op.drop_index(op.f("ix_exame_imagem_clinica_requisitante_id"), table_name="exame_imagem")
    op.drop_index(op.f("ix_exame_imagem_animal_id"), table_name="exame_imagem")
    op.drop_table("exame_imagem")
