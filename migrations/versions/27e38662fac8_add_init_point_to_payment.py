"""add init_point to payment

Revision ID: 27e38662fac8
Revises: 79f0241cd5c4
Create Date: 2025-07-20 18:36:17.762311
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "27e38662fac8"
down_revision = "79f0241cd5c4"
branch_labels = None
depends_on = None


def upgrade():
    # adiciona a coluna init_point na tabela payment
    with op.batch_alter_table("payment") as batch_op:
        batch_op.add_column(sa.Column("init_point", sa.String(), nullable=True))


def downgrade():
    # remove a coluna init_point
    with op.batch_alter_table("payment") as batch_op:
        batch_op.drop_column("init_point")
