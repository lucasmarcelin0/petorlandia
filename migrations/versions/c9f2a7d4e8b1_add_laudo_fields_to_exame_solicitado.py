"""add laudo fields to exame solicitado

Revision ID: c9f2a7d4e8b1
Revises: fb8c2d1e4a6f
Create Date: 2026-06-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'c9f2a7d4e8b1'
down_revision = 'fb8c2d1e4a6f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('exame_solicitado', schema=None) as batch_op:
        batch_op.add_column(sa.Column('laudo_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('laudo_filename', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('laudo_uploaded_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('laudo_message', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('exame_solicitado', schema=None) as batch_op:
        batch_op.drop_column('laudo_message')
        batch_op.drop_column('laudo_uploaded_at')
        batch_op.drop_column('laudo_filename')
        batch_op.drop_column('laudo_url')
