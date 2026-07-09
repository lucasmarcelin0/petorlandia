"""push subscription, carteirinha publica e assinatura de racao

Revision ID: d1ad23eb2fcb
Revises: 008ca352778e
Create Date: 2026-07-09 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd1ad23eb2fcb'
down_revision = '008ca352778e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'push_subscription',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('endpoint_hash', sa.String(length=64), nullable=False),
        sa.Column('p256dh', sa.String(length=255), nullable=False),
        sa.Column('auth', sa.String(length=255), nullable=False),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fail_count', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint_hash'),
    )
    op.create_index(op.f('ix_push_subscription_user_id'), 'push_subscription', ['user_id'], unique=False)

    op.create_table(
        'racao_assinatura',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('variant_id', sa.Integer(), nullable=True),
        sa.Column('animal_id', sa.Integer(), nullable=True),
        sa.Column('quantidade', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('frequencia_dias', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('preco_ciclo', sa.Numeric(10, 2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('mp_preapproval_id', sa.String(length=128), nullable=True),
        sa.Column('ciclos_pagos', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ultimo_ciclo_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('endereco_entrega', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['variant_id'], ['product_variant.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['animal_id'], ['animal.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_racao_assinatura_user_id'), 'racao_assinatura', ['user_id'], unique=False)
    op.create_index(op.f('ix_racao_assinatura_product_id'), 'racao_assinatura', ['product_id'], unique=False)
    op.create_index(op.f('ix_racao_assinatura_status'), 'racao_assinatura', ['status'], unique=False)

    op.add_column('animal', sa.Column('public_token', sa.String(length=32), nullable=True))
    op.create_unique_constraint('uq_animal_public_token', 'animal', ['public_token'])


def downgrade():
    op.drop_constraint('uq_animal_public_token', 'animal', type_='unique')
    op.drop_column('animal', 'public_token')
    op.drop_index(op.f('ix_racao_assinatura_status'), table_name='racao_assinatura')
    op.drop_index(op.f('ix_racao_assinatura_product_id'), table_name='racao_assinatura')
    op.drop_index(op.f('ix_racao_assinatura_user_id'), table_name='racao_assinatura')
    op.drop_table('racao_assinatura')
    op.drop_index(op.f('ix_push_subscription_user_id'), table_name='push_subscription')
    op.drop_table('push_subscription')
