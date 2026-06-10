"""add phone2 to user

Revision ID: e1a4f8b2c6d9
Revises: d9e3f1a7c2b5
Create Date: 2026-06-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'e1a4f8b2c6d9'
down_revision = 'd9e3f1a7c2b5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('phone2', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('user', 'phone2')
