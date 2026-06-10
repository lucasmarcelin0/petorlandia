"""Add preco_total e payment_id à petsitter_request

Revision ID: b8f4c2d6e9a1
Revises: a7e3b9c1d5f2
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8f4c2d6e9a1'
down_revision = 'a7e3b9c1d5f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('petsitter_request') as batch_op:
        batch_op.add_column(sa.Column('preco_total', sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column('payment_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_petsitter_request_payment',
            'payment',
            ['payment_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('petsitter_request') as batch_op:
        batch_op.drop_constraint('fk_petsitter_request_payment', type_='foreignkey')
        batch_op.drop_column('payment_id')
        batch_op.drop_column('preco_total')
