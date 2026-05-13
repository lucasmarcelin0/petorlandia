"""add grooming plans tables

Revision ID: b2d4e6f8a1c3
Revises: a3b1c9d2e8f7
Create Date: 2026-05-12 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b2d4e6f8a1c3"
down_revision = "a3b1c9d2e8f7"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "grooming_plan" not in existing_tables:
        op.create_table(
            "grooming_plan",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("clinica_id", sa.Integer(), sa.ForeignKey("clinica.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("service_type", sa.String(30), nullable=False, server_default="banho_e_tosa"),
            sa.Column("price", sa.Numeric(10, 2), nullable=False),
            sa.Column("sessions_per_month", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_grooming_plan_clinica_id", "grooming_plan", ["clinica_id"])

    if "grooming_subscription" not in existing_tables:
        op.create_table(
            "grooming_subscription",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("plan_id", sa.Integer(), sa.ForeignKey("grooming_plan.id", ondelete="CASCADE"), nullable=False),
            sa.Column("animal_id", sa.Integer(), sa.ForeignKey("animal.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("mp_preapproval_id", sa.String(128), nullable=True),
            sa.Column("sessions_used_this_month", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_grooming_subscription_plan_id", "grooming_subscription", ["plan_id"])
        op.create_index("ix_grooming_subscription_animal_id", "grooming_subscription", ["animal_id"])
        op.create_index("ix_grooming_subscription_user_id", "grooming_subscription", ["user_id"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "grooming_subscription" in existing_tables:
        op.drop_table("grooming_subscription")
    if "grooming_plan" in existing_tables:
        op.drop_table("grooming_plan")
