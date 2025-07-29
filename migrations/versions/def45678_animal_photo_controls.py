"""add photo controls to animal

Revision ID: def45678
Revises: abc12345
Create Date: 2025-08-02 12:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = 'def45678'
down_revision = 'abc12345'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('animal', schema=None) as batch_op:
        batch_op.add_column(sa.Column('photo_rotation', sa.Integer(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('photo_zoom', sa.Float(), nullable=True, server_default='1'))
        batch_op.add_column(sa.Column('photo_offset_x', sa.Float(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('photo_offset_y', sa.Float(), nullable=True, server_default='0'))


def downgrade():
    with op.batch_alter_table('animal', schema=None) as batch_op:
        batch_op.drop_column('photo_offset_y')
        batch_op.drop_column('photo_offset_x')
        batch_op.drop_column('photo_zoom')
        batch_op.drop_column('photo_rotation')
