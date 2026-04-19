"""add delivery research contact table

Revision ID: c9f4e2a1b7d3
Revises: b8c3d5e9f2a7
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9f4e2a1b7d3'
down_revision = 'b8c3d5e9f2a7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'delivery_research_contact',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tutor_id', sa.Integer(), nullable=False),
        sa.Column('sent', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['sent_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tutor_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tutor_id'),
    )
    op.create_index(
        'ix_delivery_research_contact_tutor_id',
        'delivery_research_contact',
        ['tutor_id'],
        unique=True,
    )


def downgrade():
    op.drop_index('ix_delivery_research_contact_tutor_id', table_name='delivery_research_contact')
    op.drop_table('delivery_research_contact')
