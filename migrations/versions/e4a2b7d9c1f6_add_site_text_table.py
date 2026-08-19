"""Add editable site text table.

Revision ID: e4a2b7d9c1f6
Revises: e3f9c6a24d85
Create Date: 2026-08-02 19:55:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e4a2b7d9c1f6'
down_revision = 'e3f9c6a24d85'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'site_text',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('value', sa.String(length=240), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_site_text_key'), 'site_text', ['key'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_site_text_key'), table_name='site_text')
    op.drop_table('site_text')
