"""add response collected timestamp to delivery research contact

Revision ID: f6c1a3d9e2b4
Revises: e5b9d2c4f1a8
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = 'f6c1a3d9e2b4'
down_revision = 'e5b9d2c4f1a8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('delivery_research_contact') as batch:
        batch.add_column(sa.Column('response_collected_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('delivery_research_contact') as batch:
        batch.drop_column('response_collected_at')
