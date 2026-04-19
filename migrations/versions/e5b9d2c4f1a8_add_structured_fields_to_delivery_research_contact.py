"""add structured fields to delivery research contact

Revision ID: e5b9d2c4f1a8
Revises: d4a8c1b2e6f7
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5b9d2c4f1a8'
down_revision = 'd4a8c1b2e6f7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('delivery_research_contact') as batch:
        batch.add_column(sa.Column('interest_answer', sa.String(length=20), nullable=True))
        batch.add_column(sa.Column('current_food', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('bag_size', sa.String(length=80), nullable=True))
        batch.add_column(sa.Column('price_paid', sa.String(length=80), nullable=True))
        batch.add_column(sa.Column('purchase_channel', sa.String(length=120), nullable=True))
        batch.add_column(sa.Column('duration_estimate', sa.String(length=120), nullable=True))
        batch.add_column(sa.Column('response_notes', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('delivery_research_contact') as batch:
        batch.drop_column('response_notes')
        batch.drop_column('duration_estimate')
        batch.drop_column('purchase_channel')
        batch.drop_column('price_paid')
        batch.drop_column('bag_size')
        batch.drop_column('current_food')
        batch.drop_column('interest_answer')
