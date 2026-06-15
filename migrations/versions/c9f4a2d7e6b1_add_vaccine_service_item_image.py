"""add vaccine service item image

Revision ID: c9f4a2d7e6b1
Revises: b6e2a8c4d9f1
Create Date: 2026-06-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'c9f4a2d7e6b1'
down_revision = 'b6e2a8c4d9f1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'vaccine_service_item',
        sa.Column('image_url', sa.String(length=255), nullable=True),
    )


def downgrade():
    op.drop_column('vaccine_service_item', 'image_url')
