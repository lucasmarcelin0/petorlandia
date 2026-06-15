"""add feed store onboarding invites

Revision ID: a7d4e2c9f1b6
Revises: a1d4f7c2e9b3
Create Date: 2026-06-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'a7d4e2c9f1b6'
down_revision = 'a1d4f7c2e9b3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'casa_de_racao_onboarding_invite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['casa_de_racao_id'],
            ['casa_de_racao.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(
        op.f('ix_casa_de_racao_onboarding_invite_casa_de_racao_id'),
        'casa_de_racao_onboarding_invite',
        ['casa_de_racao_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_casa_de_racao_onboarding_invite_token_hash'),
        'casa_de_racao_onboarding_invite',
        ['token_hash'],
        unique=True,
    )


def downgrade():
    op.drop_index(
        op.f('ix_casa_de_racao_onboarding_invite_token_hash'),
        table_name='casa_de_racao_onboarding_invite',
    )
    op.drop_index(
        op.f('ix_casa_de_racao_onboarding_invite_casa_de_racao_id'),
        table_name='casa_de_racao_onboarding_invite',
    )
    op.drop_table('casa_de_racao_onboarding_invite')
