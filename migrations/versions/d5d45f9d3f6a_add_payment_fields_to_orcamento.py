"""add payment metadata to orcamento

Revision ID: d5d45f9d3f6a
Revises: 1a9f4e4c5b2c
Create Date: 2025-05-07 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5d45f9d3f6a'
down_revision = '1a9f4e4c5b2c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orcamento', sa.Column('payment_link', sa.Text(), nullable=True))
    op.add_column('orcamento', sa.Column('payment_reference', sa.String(length=120), nullable=True))
    op.add_column('orcamento', sa.Column('payment_status', sa.String(length=20), nullable=True))
    op.add_column('orcamento', sa.Column('paid_at', sa.DateTime(), nullable=True))
    op.create_index('ix_orcamento_payment_reference', 'orcamento', ['payment_reference'], unique=False)
    op.create_index('ix_orcamento_payment_status', 'orcamento', ['payment_status'], unique=False)


def downgrade():
    op.drop_index('ix_orcamento_payment_status', table_name='orcamento')
    op.drop_index('ix_orcamento_payment_reference', table_name='orcamento')
    op.drop_column('orcamento', 'paid_at')
    op.drop_column('orcamento', 'payment_status')
    op.drop_column('orcamento', 'payment_reference')
    op.drop_column('orcamento', 'payment_link')
