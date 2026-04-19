"""add replied and recorded fields to delivery research contact

Revision ID: d4a8c1b2e6f7
Revises: c9f4e2a1b7d3
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4a8c1b2e6f7'
down_revision = 'c9f4e2a1b7d3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('delivery_research_contact') as batch:
        batch.add_column(sa.Column('replied', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('replied_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('replied_by_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('recorded', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('recorded_by_id', sa.Integer(), nullable=True))
        batch.create_foreign_key(
            'fk_delivery_research_contact_replied_by_id_user',
            'user',
            ['replied_by_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch.create_foreign_key(
            'fk_delivery_research_contact_recorded_by_id_user',
            'user',
            ['recorded_by_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('delivery_research_contact') as batch:
        batch.drop_constraint('fk_delivery_research_contact_recorded_by_id_user', type_='foreignkey')
        batch.drop_constraint('fk_delivery_research_contact_replied_by_id_user', type_='foreignkey')
        batch.drop_column('recorded_by_id')
        batch.drop_column('recorded_at')
        batch.drop_column('recorded')
        batch.drop_column('replied_by_id')
        batch.drop_column('replied_at')
        batch.drop_column('replied')
