"""add photo crop offsets to user

Revision ID: abc12345
Revises: be9a1dc58c6f
Create Date: 2025-08-02 00:00:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'abc12345'
down_revision = 'be9a1dc58c6f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('photo_offset_x', sa.Float(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('photo_offset_y', sa.Float(), nullable=True, server_default='0'))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('photo_offset_y')
        batch_op.drop_column('photo_offset_x')
