"""add cancel reason to delivery request

Revision ID: ede02af536ac
Revises: e8aff173e0fe
Create Date: 2025-08-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'ede02af536ac'
down_revision = 'e8aff173e0fe'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('delivery_request', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cancel_reason', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('delivery_request', schema=None) as batch_op:
        batch_op.drop_column('cancel_reason')
