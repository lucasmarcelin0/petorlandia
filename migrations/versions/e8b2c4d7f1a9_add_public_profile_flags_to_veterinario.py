"""add public profile flags to veterinario

Revision ID: e8b2c4d7f1a9
Revises: d4f7a9c2e6b1
Create Date: 2026-06-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'e8b2c4d7f1a9'
down_revision = 'd4f7a9c2e6b1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'veterinario',
        sa.Column('public_profile_type', sa.String(length=20), nullable=False, server_default='profissional'),
    )
    op.add_column(
        'veterinario',
        sa.Column('public_visible', sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade():
    op.drop_column('veterinario', 'public_visible')
    op.drop_column('veterinario', 'public_profile_type')
