"""Add privacy-preserving product event table.

Revision ID: c4a8f2d71e90
Revises: b8d1e4f70c93
Create Date: 2026-07-29 21:10:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4a8f2d71e90'
down_revision = 'b8d1e4f70c93'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'product_event',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('event_name', sa.String(length=80), nullable=False),
        sa.Column('anonymous_id', sa.String(length=64), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('source_path', sa.String(length=300), nullable=True),
        sa.Column('referrer_host', sa.String(length=180), nullable=True),
        sa.Column('utm_source', sa.String(length=120), nullable=True),
        sa.Column('utm_medium', sa.String(length=120), nullable=True),
        sa.Column('utm_campaign', sa.String(length=160), nullable=True),
        sa.Column('properties', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    for column in (
        'event_name', 'anonymous_id', 'session_id', 'user_id',
        'utm_source', 'created_at',
    ):
        op.create_index(
            f'ix_product_event_{column}',
            'product_event',
            [column],
            unique=False,
        )


def downgrade():
    op.drop_table('product_event')
