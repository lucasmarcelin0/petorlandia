"""Contabilidade embutida: categoria da despesa e contador da clínica.

Revision ID: b3d5f7a9c1e2
Revises: a7c3e9f1d2b4
Create Date: 2026-11-21 10:00:00.000000

``accounting_accounts`` ganha ``category`` (anulável, sem tocar nos valores
existentes). Duas tabelas novas: configuração do contador por clínica e o
registro de cada fechamento mensal enviado.
"""
from alembic import op
import sqlalchemy as sa

revision = "b3d5f7a9c1e2"
down_revision = "a7c3e9f1d2b4"
branch_labels = None
depends_on = None


def upgrade():
    inspetor = sa.inspect(op.get_bind())
    tabelas = set(inspetor.get_table_names())

    if "accounting_accounts" in tabelas:
        colunas = {c["name"] for c in inspetor.get_columns("accounting_accounts")}
        if "category" not in colunas:
            with op.batch_alter_table("accounting_accounts") as batch:
                batch.add_column(sa.Column("category", sa.String(40), nullable=True))

    if "clinic_accounting_settings" not in tabelas:
        op.create_table(
            "clinic_accounting_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinica.id"), nullable=False, unique=True),
            sa.Column("contador_nome", sa.String(120)),
            sa.Column("contador_email", sa.String(180)),
            sa.Column("envio_automatico", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "accounting_delivery" not in tabelas:
        op.create_table(
            "accounting_delivery",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinica.id"), nullable=False),
            sa.Column("month", sa.Date(), nullable=False),
            sa.Column("sent_to", sa.String(180), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("sent_by_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
            sa.Column("automatic", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_index("ix_accounting_delivery_clinic_id", "accounting_delivery", ["clinic_id"])


def downgrade():
    op.drop_index("ix_accounting_delivery_clinic_id", table_name="accounting_delivery")
    op.drop_table("accounting_delivery")
    op.drop_table("clinic_accounting_settings")
    with op.batch_alter_table("accounting_accounts") as batch:
        batch.drop_column("category")
