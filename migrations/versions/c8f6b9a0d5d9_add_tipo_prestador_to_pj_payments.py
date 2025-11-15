"""add tipo_prestador to pj_payments

Revision ID: c8f6b9a0d5d9
Revises: a99a4be65f35
Create Date: 2025-11-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'c8f6b9a0d5d9'
down_revision = 'a99a4be65f35'
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    if not _column_exists('pj_payments', 'tipo_prestador'):
        op.add_column(
            'pj_payments',
            sa.Column(
                'tipo_prestador',
                sa.String(length=50),
                nullable=True,
                server_default='especialista',
            ),
        )
        op.execute(
            "UPDATE pj_payments SET tipo_prestador = 'especialista' WHERE tipo_prestador IS NULL"
        )


def downgrade():
    if _column_exists('pj_payments', 'tipo_prestador'):
        op.drop_column('pj_payments', 'tipo_prestador')
