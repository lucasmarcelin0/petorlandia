"""add fiscal fields to product

Revision ID: 6d2f1c0b8b2a
Revises: 8f511c25d426
Create Date: 2026-01-30 23:59:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6d2f1c0b8b2a"
down_revision = "8f511c25d426"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("product")}

    if "mp_category_id" not in columns:
        op.add_column(
            "product",
            sa.Column("mp_category_id", sa.String(length=50), nullable=True),
        )
    if "ncm" not in columns:
        op.add_column("product", sa.Column("ncm", sa.String(length=10), nullable=True))
    if "cfop" not in columns:
        op.add_column("product", sa.Column("cfop", sa.String(length=10), nullable=True))
    if "cst" not in columns:
        op.add_column("product", sa.Column("cst", sa.String(length=5), nullable=True))
    if "csosn" not in columns:
        op.add_column("product", sa.Column("csosn", sa.String(length=5), nullable=True))
    if "origem" not in columns:
        op.add_column("product", sa.Column("origem", sa.String(length=2), nullable=True))
    if "unidade" not in columns:
        op.add_column("product", sa.Column("unidade", sa.String(length=10), nullable=True))
    if "aliquota_icms" not in columns:
        op.add_column(
            "product",
            sa.Column("aliquota_icms", sa.Numeric(10, 4), nullable=True),
        )
    if "aliquota_pis" not in columns:
        op.add_column(
            "product",
            sa.Column("aliquota_pis", sa.Numeric(10, 4), nullable=True),
        )
    if "aliquota_cofins" not in columns:
        op.add_column(
            "product",
            sa.Column("aliquota_cofins", sa.Numeric(10, 4), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("product")}

    if "aliquota_cofins" in columns:
        op.drop_column("product", "aliquota_cofins")
    if "aliquota_pis" in columns:
        op.drop_column("product", "aliquota_pis")
    if "aliquota_icms" in columns:
        op.drop_column("product", "aliquota_icms")
    if "unidade" in columns:
        op.drop_column("product", "unidade")
    if "origem" in columns:
        op.drop_column("product", "origem")
    if "csosn" in columns:
        op.drop_column("product", "csosn")
    if "cst" in columns:
        op.drop_column("product", "cst")
    if "cfop" in columns:
        op.drop_column("product", "cfop")
    if "ncm" in columns:
        op.drop_column("product", "ncm")
    if "mp_category_id" in columns:
        op.drop_column("product", "mp_category_id")
