"""add payment fields to orcamento

Revision ID: 4f52fbdb09f1
Revises: 3b4c5d6e7f80
Create Date: 2024-05-22 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '4f52fbdb09f1'
down_revision = '3b4c5d6e7f80'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orcamento', sa.Column('payment_link', sa.Text(), nullable=True))
    op.add_column('orcamento', sa.Column('payment_reference', sa.String(length=120), nullable=True))
    op.add_column('orcamento', sa.Column('payment_status', sa.String(length=20), nullable=True))
    op.add_column('orcamento', sa.Column('paid_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_orcamento_payment_reference'), 'orcamento', ['payment_reference'], unique=False)
    op.create_index(op.f('ix_orcamento_payment_status'), 'orcamento', ['payment_status'], unique=False)
    op.create_index(op.f('ix_orcamento_paid_at'), 'orcamento', ['paid_at'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_orcamento_paid_at'), table_name='orcamento')
    op.drop_index(op.f('ix_orcamento_payment_status'), table_name='orcamento')
    op.drop_index(op.f('ix_orcamento_payment_reference'), table_name='orcamento')
    op.drop_column('orcamento', 'paid_at')
    op.drop_column('orcamento', 'payment_status')
    op.drop_column('orcamento', 'payment_reference')
    op.drop_column('orcamento', 'payment_link')
