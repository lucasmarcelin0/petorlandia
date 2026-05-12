"""add clinica fields to product

Revision ID: a3b1c9d2e8f7
Revises: f1b4d7c8e2a3
Create Date: 2026-05-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a3b1c9d2e8f7"
down_revision = "f1b4d7c8e2a3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("product")}

    if "clinica_id" not in columns:
        op.add_column(
            "product",
            sa.Column("clinica_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_product_clinica_id",
            "product",
            "clinica",
            ["clinica_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_product_clinica_id", "product", ["clinica_id"])

    if "clinic_inventory_item_id" not in columns:
        op.add_column(
            "product",
            sa.Column("clinic_inventory_item_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_product_clinic_inventory_item_id",
            "product",
            "clinic_inventory_item",
            ["clinic_inventory_item_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if "status" not in columns:
        op.add_column(
            "product",
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("product")}

    if "status" in columns:
        op.drop_column("product", "status")

    if "clinic_inventory_item_id" in columns:
        op.drop_constraint("fk_product_clinic_inventory_item_id", "product", type_="foreignkey")
        op.drop_column("product", "clinic_inventory_item_id")

    if "clinica_id" in columns:
        op.drop_index("ix_product_clinica_id", table_name="product")
        op.drop_constraint("fk_product_clinica_id", "product", type_="foreignkey")
        op.drop_column("product", "clinica_id")
