"""Add site_flag table

Revision ID: fb9f33ae1c23
Revises: f7a3c9d2e1b4
Create Date: 2026-07-01 20:25:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fb9f33ae1c23'
down_revision = 'f7a3c9d2e1b4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'site_flag',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('value', sa.Boolean(), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_site_flag_key'), 'site_flag', ['key'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_site_flag_key'), table_name='site_flag')
    op.drop_table('site_flag')
