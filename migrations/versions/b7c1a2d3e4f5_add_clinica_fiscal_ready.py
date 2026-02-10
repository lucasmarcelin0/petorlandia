"""add fiscal_ready flag to clinica

Revision ID: b7c1a2d3e4f5
Revises: 6d2f1c0b8b2a
Create Date: 2026-02-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7c1a2d3e4f5"
down_revision = "6d2f1c0b8b2a"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("clinica")}

    if "fiscal_ready" not in columns:
        op.add_column(
            "clinica",
            sa.Column("fiscal_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.alter_column("clinica", "fiscal_ready", server_default=None)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("clinica")}

    if "fiscal_ready" in columns:
        op.drop_column("clinica", "fiscal_ready")
