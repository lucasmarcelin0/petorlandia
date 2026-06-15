"""add cidade to vaccine_service_item

Revision ID: b7c4e2f1a8d9
Revises: fb8c2d1e4a6f
Create Date: 2026-06-15

"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c4e2f1a8d9'
down_revision = 'fb8c2d1e4a6f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'vaccine_service_item',
        sa.Column('cidade', sa.String(100), nullable=True),
    )
    op.create_index('ix_vaccine_service_item_cidade', 'vaccine_service_item', ['cidade'])
    op.execute("UPDATE vaccine_service_item SET cidade = 'Orlândia' WHERE cidade IS NULL")


def downgrade():
    op.drop_index('ix_vaccine_service_item_cidade', table_name='vaccine_service_item')
    op.drop_column('vaccine_service_item', 'cidade')
