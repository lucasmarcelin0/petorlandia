"""add payment fields to orcamento

Revision ID: 4d593a92d5c6
Revises: fe3b6f9d7e2d
Create Date: 2024-05-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '4d593a92d5c6'
down_revision = 'fe3b6f9d7e2d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orcamento', sa.Column('payment_link', sa.Text(), nullable=True))
    op.add_column('orcamento', sa.Column('payment_reference', sa.String(length=120), nullable=True))
    op.add_column('orcamento', sa.Column('payment_status', sa.String(length=20), nullable=True))
    op.add_column('orcamento', sa.Column('paid_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_orcamento_payment_reference'), 'orcamento', ['payment_reference'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_orcamento_payment_reference'), table_name='orcamento')
    op.drop_column('orcamento', 'paid_at')
    op.drop_column('orcamento', 'payment_status')
    op.drop_column('orcamento', 'payment_reference')
    op.drop_column('orcamento', 'payment_link')
