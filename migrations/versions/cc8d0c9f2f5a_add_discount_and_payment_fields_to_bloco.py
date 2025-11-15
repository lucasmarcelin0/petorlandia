"""add discount and payment fields to bloco orcamento

Revision ID: cc8d0c9f2f5a
Revises: c49321bb88a2
Create Date: 2025-03-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'cc8d0c9f2f5a'
down_revision = 'c49321bb88a2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bloco_orcamento', sa.Column('discount_percent', sa.Numeric(5, 2), nullable=True))
    op.add_column('bloco_orcamento', sa.Column('discount_value', sa.Numeric(10, 2), nullable=True))
    op.add_column('bloco_orcamento', sa.Column('tutor_notes', sa.Text(), nullable=True))
    op.add_column('bloco_orcamento', sa.Column('net_total', sa.Numeric(10, 2), nullable=True))
    op.add_column('bloco_orcamento', sa.Column('payment_status', sa.String(length=20), server_default='draft', nullable=False))
    op.add_column('bloco_orcamento', sa.Column('payment_link', sa.Text(), nullable=True))
    op.add_column('bloco_orcamento', sa.Column('payment_reference', sa.String(length=120), nullable=True))
    op.alter_column('bloco_orcamento', 'payment_status', server_default=None)


def downgrade():
    op.drop_column('bloco_orcamento', 'payment_reference')
    op.drop_column('bloco_orcamento', 'payment_link')
    op.drop_column('bloco_orcamento', 'payment_status')
    op.drop_column('bloco_orcamento', 'net_total')
    op.drop_column('bloco_orcamento', 'tutor_notes')
    op.drop_column('bloco_orcamento', 'discount_value')
    op.drop_column('bloco_orcamento', 'discount_percent')
