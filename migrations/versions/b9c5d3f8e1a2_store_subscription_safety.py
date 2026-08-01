"""Make store subscriptions explicit, auditable and idempotent.

Revision ID: b9c5d3f8e1a2
Revises: a8f4c2e7d9b1
Create Date: 2026-08-01 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b9c5d3f8e1a2"
down_revision = "a8f4c2e7d9b1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("product") as batch_op:
        batch_op.add_column(sa.Column("subscription_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("subscription_discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("subscription_shipping_fee", sa.Numeric(10, 2), nullable=False, server_default="0"))

    with op.batch_alter_table("racao_assinatura") as batch_op:
        batch_op.add_column(sa.Column("preco_unitario", sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column("frete_ciclo", sa.Numeric(10, 2), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("init_point", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.String(500), nullable=True))
        batch_op.add_column(sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("consent_ip", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("consent_user_agent", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("terms_version", sa.String(32), nullable=True))

    # Preserva registros legados e passa a garantir o endereco nos novos ciclos.
    op.execute("UPDATE racao_assinatura SET endereco_entrega = '' WHERE endereco_entrega IS NULL")
    with op.batch_alter_table("racao_assinatura") as batch_op:
        batch_op.alter_column(
            "endereco_entrega",
            existing_type=sa.String(255),
            nullable=False,
        )

    op.create_table(
        "racao_assinatura_ciclo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assinatura_id", sa.Integer(), nullable=False),
        sa.Column("provider_payment_id", sa.String(128), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("valor", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assinatura_id"], ["racao_assinatura.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["order.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
        sa.UniqueConstraint("provider_payment_id"),
    )
    op.create_index(
        "ix_racao_assinatura_ciclo_assinatura_id",
        "racao_assinatura_ciclo",
        ["assinatura_id"],
    )


def downgrade():
    op.drop_index("ix_racao_assinatura_ciclo_assinatura_id", table_name="racao_assinatura_ciclo")
    op.drop_table("racao_assinatura_ciclo")

    with op.batch_alter_table("racao_assinatura") as batch_op:
        batch_op.alter_column(
            "endereco_entrega",
            existing_type=sa.String(255),
            nullable=True,
        )
        batch_op.drop_column("terms_version")
        batch_op.drop_column("consent_user_agent")
        batch_op.drop_column("consent_ip")
        batch_op.drop_column("consent_at")
        batch_op.drop_column("last_error")
        batch_op.drop_column("init_point")
        batch_op.drop_column("frete_ciclo")
        batch_op.drop_column("preco_unitario")

    with op.batch_alter_table("product") as batch_op:
        batch_op.drop_column("subscription_shipping_fee")
        batch_op.drop_column("subscription_discount_percent")
        batch_op.drop_column("subscription_enabled")
