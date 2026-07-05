"""Freight payout tracking + receipt reminder timestamp

- delivery_request: frete_valor (congelado na conclusão), frete_pago_em e
  frete_pago_por_id (lote semanal de repasse ao entregador)
- order: receipt_reminder_at (anti-spam do lembrete de confirmação)

Revision ID: e2a4c6d8f0b1
Revises: c9d1e3f5a7b2
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa


revision = 'e2a4c6d8f0b1'
down_revision = 'c9d1e3f5a7b2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('receipt_reminder_at', sa.DateTime(timezone=True), nullable=True)
        )

    with op.batch_alter_table('delivery_request', schema=None) as batch_op:
        batch_op.add_column(sa.Column('frete_valor', sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column('frete_pago_em', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('frete_pago_por_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_delivery_request_frete_pago_por',
            'user',
            ['frete_pago_por_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('delivery_request', schema=None) as batch_op:
        batch_op.drop_constraint('fk_delivery_request_frete_pago_por', type_='foreignkey')
        batch_op.drop_column('frete_pago_por_id')
        batch_op.drop_column('frete_pago_em')
        batch_op.drop_column('frete_valor')

    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('receipt_reminder_at')
