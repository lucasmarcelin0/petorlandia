"""merge heads before alias table

Revision ID: c6c8c78ce463
Revises: 7ddc4b706765, 7eb22b9c3ba9
Create Date: 2026-05-04 19:46:19.140800

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c6c8c78ce463'
down_revision = ('7ddc4b706765', '7eb22b9c3ba9')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
