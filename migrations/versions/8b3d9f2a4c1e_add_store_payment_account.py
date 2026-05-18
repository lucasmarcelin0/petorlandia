"""add store payment account

Revision ID: 8b3d9f2a4c1e
Revises: 6af8d65efabb
Create Date: 2026-05-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '8b3d9f2a4c1e'
down_revision = '6af8d65efabb'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'store_payment_account',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=40), nullable=False),
        sa.Column('provider_user_id', sa.String(length=80), nullable=True),
        sa.Column('public_key', sa.String(length=255), nullable=True),
        sa.Column('access_token_encrypted', sa.Text(), nullable=True),
        sa.Column('refresh_token_encrypted', sa.Text(), nullable=True),
        sa.Column('oauth_state', sa.String(length=128), nullable=True),
        sa.Column('code_verifier_encrypted', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_refreshed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('casa_de_racao_id', 'provider', name='uq_store_payment_provider'),
    )
    op.create_index(
        op.f('ix_store_payment_account_casa_de_racao_id'),
        'store_payment_account',
        ['casa_de_racao_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_store_payment_account_oauth_state'),
        'store_payment_account',
        ['oauth_state'],
        unique=True,
    )
    op.create_index(
        op.f('ix_store_payment_account_provider_user_id'),
        'store_payment_account',
        ['provider_user_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f('ix_store_payment_account_provider_user_id'), table_name='store_payment_account')
    op.drop_index(op.f('ix_store_payment_account_oauth_state'), table_name='store_payment_account')
    op.drop_index(op.f('ix_store_payment_account_casa_de_racao_id'), table_name='store_payment_account')
    op.drop_table('store_payment_account')
