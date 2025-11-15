"""ensure discount columns exist on bloco_orcamento

Revision ID: fe3b6f9d7e2d
Revises: cc8d0c9f2f5a
Create Date: 2025-02-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'fe3b6f9d7e2d'
down_revision = 'cc8d0c9f2f5a'
branch_labels = None
depends_on = None


def _add_column_if_missing(table_name, column):
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    if column.name not in columns:
        op.add_column(table_name, column)


def upgrade():
    _add_column_if_missing('bloco_orcamento', sa.Column('discount_percent', sa.Numeric(5, 2), nullable=True))
    _add_column_if_missing('bloco_orcamento', sa.Column('discount_value', sa.Numeric(10, 2), nullable=True))
    _add_column_if_missing('bloco_orcamento', sa.Column('tutor_notes', sa.Text(), nullable=True))
    _add_column_if_missing('bloco_orcamento', sa.Column('net_total', sa.Numeric(10, 2), nullable=True))
    _add_column_if_missing('bloco_orcamento', sa.Column('payment_status', sa.String(length=20), nullable=False, server_default='draft'))
    _add_column_if_missing('bloco_orcamento', sa.Column('payment_link', sa.Text(), nullable=True))
    _add_column_if_missing('bloco_orcamento', sa.Column('payment_reference', sa.String(length=120), nullable=True))
    # remove server default once column exists
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('bloco_orcamento')]
    if 'payment_status' in columns:
        op.alter_column('bloco_orcamento', 'payment_status', server_default=None, existing_type=sa.String(length=20))


def downgrade():
    # This migration is idempotent; we only drop columns if they exist to avoid issues
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('bloco_orcamento')]
    for name in ['payment_reference', 'payment_link', 'payment_status', 'net_total', 'tutor_notes', 'discount_value', 'discount_percent']:
        if name in columns:
            op.drop_column('bloco_orcamento', name)
            columns.remove(name)
