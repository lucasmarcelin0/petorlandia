"""add clinic photo fields

Revision ID: 1a2b3c4d5e6f
Revises: b27a5b6156e3
Create Date: 2025-02-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1a2b3c4d5e6f'
down_revision = 'b27a5b6156e3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clinica', schema=None) as batch_op:
        batch_op.add_column(sa.Column('photo_rotation', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('photo_zoom', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('photo_offset_x', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('photo_offset_y', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('clinica', schema=None) as batch_op:
        batch_op.drop_column('photo_offset_y')
        batch_op.drop_column('photo_offset_x')
        batch_op.drop_column('photo_zoom')
        batch_op.drop_column('photo_rotation')
