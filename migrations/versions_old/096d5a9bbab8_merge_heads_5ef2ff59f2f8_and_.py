"""Merge heads 5ef2ff59f2f8 and be9a1dc58c6f

Revision ID: 096d5a9bbab8
Revises: 5ef2ff59f2f8, be9a1dc58c6f
Create Date: 2025-07-29 07:06:00.925031

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '096d5a9bbab8'
down_revision = ('5ef2ff59f2f8', 'be9a1dc58c6f')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
