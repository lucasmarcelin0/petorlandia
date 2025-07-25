"""Merge correto de branches de migration

Revision ID: 9b1c12345678
Revises: 59ba2d1f5928, 621bcc65bd3e
Create Date: 2025-07-24 19:48:57.278193

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9b1c12345678'
down_revision = ('59ba2d1f5928', '621bcc65bd3e')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
