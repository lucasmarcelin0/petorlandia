"""Add auditable veterinarian membership subscriptions and charges.

Revision ID: a8f4c2e7d9b1
Revises: e6c2a9f4b8d1
Create Date: 2026-08-01 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a8f4c2e7d9b1"
down_revision = "e6c2a9f4b8d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "veterinarian_membership_subscription",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_preapproval_id", sa.String(length=64), nullable=True),
        sa.Column("external_reference", sa.String(length=255), nullable=False),
        sa.Column("plan_code", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_status", sa.String(length=32), nullable=True),
        sa.Column("init_point", sa.Text(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["membership_id"], ["veterinarian_membership.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_reference"),
        sa.UniqueConstraint("provider_preapproval_id"),
    )
    op.create_index(
        "ix_vet_membership_subscription_membership_id",
        "veterinarian_membership_subscription",
        ["membership_id"],
    )
    op.create_index(
        "ix_vet_membership_subscription_status",
        "veterinarian_membership_subscription",
        ["status"],
    )

    op.create_table(
        "veterinarian_membership_charge",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=64), nullable=False),
        sa.Column("provider_invoice_id", sa.String(length=64), nullable=True),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("cycle_days", sa.Integer(), nullable=False),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["membership_id"], ["veterinarian_membership.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["veterinarian_membership_subscription.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_invoice_id"),
        sa.UniqueConstraint("provider_payment_id"),
    )
    op.create_index(
        "ix_vet_membership_charge_membership_id",
        "veterinarian_membership_charge",
        ["membership_id"],
    )
    op.create_index(
        "ix_vet_membership_charge_subscription_id",
        "veterinarian_membership_charge",
        ["subscription_id"],
    )
    op.create_index(
        "ix_vet_membership_charge_external_reference",
        "veterinarian_membership_charge",
        ["external_reference"],
    )
    op.create_index(
        "ix_vet_membership_charge_status",
        "veterinarian_membership_charge",
        ["status"],
    )


def downgrade():
    op.drop_index(
        "ix_vet_membership_charge_status",
        table_name="veterinarian_membership_charge",
    )
    op.drop_index(
        "ix_vet_membership_charge_external_reference",
        table_name="veterinarian_membership_charge",
    )
    op.drop_index(
        "ix_vet_membership_charge_subscription_id",
        table_name="veterinarian_membership_charge",
    )
    op.drop_index(
        "ix_vet_membership_charge_membership_id",
        table_name="veterinarian_membership_charge",
    )
    op.drop_table("veterinarian_membership_charge")
    op.drop_index(
        "ix_vet_membership_subscription_status",
        table_name="veterinarian_membership_subscription",
    )
    op.drop_index(
        "ix_vet_membership_subscription_membership_id",
        table_name="veterinarian_membership_subscription",
    )
    op.drop_table("veterinarian_membership_subscription")
