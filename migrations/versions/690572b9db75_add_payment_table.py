"""add payment table

Revision ID: 690572b9db75
Revises: c7e0d6072efa
Create Date: 2025-07-19 12:35:47.822424
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM


# revision identifiers, used by Alembic.
revision = '690572b9db75'
down_revision = 'c7e0d6072efa'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'payment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('order.id'), nullable=False),
        sa.Column('method', ENUM('PIX', 'CREDIT_CARD', 'DEBIT_CARD', 'BOLETO', name='paymentmethod', create_type=False), nullable=False),
        sa.Column('status', ENUM('PENDING', 'COMPLETED', 'FAILED', name='paymentstatus', create_type=False), nullable=True),
        sa.Column('transaction_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False)
    )

    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.alter_column('user_id',
                              existing_type=sa.INTEGER(),
                              nullable=True)


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.alter_column('user_id',
                              existing_type=sa.INTEGER(),
                              nullable=False)

    op.drop_table('payment')
