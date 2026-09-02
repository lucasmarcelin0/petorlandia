"""Adiciona complemento estruturado e revisao das fichas SINAN.

Revision ID: d4b7a2c91e60
Revises: c8a3f19d47b2
"""

from alembic import op
import sqlalchemy as sa


revision = "d4b7a2c91e60"
down_revision = "c8a3f19d47b2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sfa_sinan_log") as batch_op:
        batch_op.add_column(sa.Column("dados_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("fonte_complementar", sa.String(length=60), nullable=True))
        batch_op.add_column(
            sa.Column(
                "revisao_status",
                sa.String(length=20),
                server_default="NAO_ESTRUTURADO",
                nullable=False,
            )
        )
        batch_op.create_index("ix_sfa_sinan_log_revisao_status", ["revisao_status"], unique=False)


def downgrade():
    with op.batch_alter_table("sfa_sinan_log") as batch_op:
        batch_op.drop_index("ix_sfa_sinan_log_revisao_status")
        batch_op.drop_column("revisao_status")
        batch_op.drop_column("fonte_complementar")
        batch_op.drop_column("dados_json")
