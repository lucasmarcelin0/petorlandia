"""add payment fields to bloco_exames and exame_solicitado

Adiciona colunas de controle financeiro (payment_status, payment_link,
payment_reference, paid_at) em bloco_exames e exame_solicitado para viabilizar
a contratação e pagamento dos exames via Mercado Pago.

Revision ID: c2f6b3d0e200
Revises: b1e5a2c9f100
Create Date: 2026-09-08

"""
from alembic import op
import sqlalchemy as sa


revision = 'c2f6b3d0e200'
down_revision = 'b1e5a2c9f100'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table('bloco_exames'):
        bloco_cols = [col['name'] for col in inspector.get_columns('bloco_exames')]
        if 'payment_status' not in bloco_cols:
            op.add_column('bloco_exames', sa.Column('payment_status', sa.String(20), nullable=True, server_default='pendente'))
            try:
                op.create_index(op.f('ix_bloco_exames_payment_status'), 'bloco_exames', ['payment_status'], unique=False)
            except Exception:
                pass
        if 'payment_link' not in bloco_cols:
            op.add_column('bloco_exames', sa.Column('payment_link', sa.Text(), nullable=True))
        if 'payment_reference' not in bloco_cols:
            op.add_column('bloco_exames', sa.Column('payment_reference', sa.String(120), nullable=True))
            try:
                op.create_index(op.f('ix_bloco_exames_payment_reference'), 'bloco_exames', ['payment_reference'], unique=False)
            except Exception:
                pass
        if 'paid_at' not in bloco_cols:
            op.add_column('bloco_exames', sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True))
            try:
                op.create_index(op.f('ix_bloco_exames_paid_at'), 'bloco_exames', ['paid_at'], unique=False)
            except Exception:
                pass

    if inspector.has_table('exame_solicitado'):
        exame_cols = [col['name'] for col in inspector.get_columns('exame_solicitado')]
        if 'payment_status' not in exame_cols:
            op.add_column('exame_solicitado', sa.Column('payment_status', sa.String(20), nullable=True, server_default='pendente'))
            try:
                op.create_index(op.f('ix_exame_solicitado_payment_status'), 'exame_solicitado', ['payment_status'], unique=False)
            except Exception:
                pass


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table('exame_solicitado'):
        exame_cols = [col['name'] for col in inspector.get_columns('exame_solicitado')]
        if 'payment_status' in exame_cols:
            try:
                op.drop_index(op.f('ix_exame_solicitado_payment_status'), table_name='exame_solicitado')
            except Exception:
                pass
            op.drop_column('exame_solicitado', 'payment_status')

    if inspector.has_table('bloco_exames'):
        bloco_cols = [col['name'] for col in inspector.get_columns('bloco_exames')]
        for col, ix in [
            ('paid_at', 'ix_bloco_exames_paid_at'),
            ('payment_reference', 'ix_bloco_exames_payment_reference'),
            ('payment_status', 'ix_bloco_exames_payment_status'),
            ('payment_link', None),
        ]:
            if col in bloco_cols:
                if ix:
                    try:
                        op.drop_index(op.f(ix), table_name='bloco_exames')
                    except Exception:
                        pass
                op.drop_column('bloco_exames', col)
