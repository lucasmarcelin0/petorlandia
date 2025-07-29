"""add photo rotation and zoom to user

Revision ID: be9a1dc58c6f
Revises: 07c9382e9aad
Create Date: 2025-08-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = 'be9a1dc58c6f'
down_revision = '07c9382e9aad'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('photo_rotation', sa.Integer(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('photo_zoom', sa.Float(), nullable=True, server_default='1'))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('photo_zoom')
        batch_op.drop_column('photo_rotation')
