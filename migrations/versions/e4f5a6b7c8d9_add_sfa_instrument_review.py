"""add sfa instrument review

Revision ID: e4f5a6b7c8d9
Revises: d7e1f4a9c2b8
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa


revision = "e4f5a6b7c8d9"
down_revision = "d7e1f4a9c2b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sfa_instrument_review",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("reviewer_name", sa.String(length=160), nullable=True),
        sa.Column("reviewer_email", sa.String(length=180), nullable=True),
        sa.Column("reviewer_profile", sa.String(length=180), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=60), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sfa_instrument_review_kind",
        "sfa_instrument_review",
        ["kind"],
        unique=False,
    )
    op.create_index(
        "ix_sfa_instrument_review_created_at",
        "sfa_instrument_review",
        ["created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_sfa_instrument_review_created_at", table_name="sfa_instrument_review")
    op.drop_index("ix_sfa_instrument_review_kind", table_name="sfa_instrument_review")
    op.drop_table("sfa_instrument_review")
