"""add plantao_horas to pj_payments

Revision ID: 0f4e2f8b7b1c
Revises: 9e7f28873ee3
Create Date: 2025-11-25 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '0f4e2f8b7b1c'
down_revision = '9e7f28873ee3'
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    if not _column_exists('pj_payments', 'plantao_horas'):
        op.add_column('pj_payments', sa.Column('plantao_horas', sa.Numeric(5, 2), nullable=True))


def downgrade():
    if _column_exists('pj_payments', 'plantao_horas'):
        op.drop_column('pj_payments', 'plantao_horas')
