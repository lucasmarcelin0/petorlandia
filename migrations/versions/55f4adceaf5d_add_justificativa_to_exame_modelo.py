"""add justificativa to exame_modelo

Revision ID: 55f4adceaf5d
Revises: 1a2b3c4d5e6f
Create Date: 2025-10-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '55f4adceaf5d'
down_revision = '1a2b3c4d5e6f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('exame_modelo', schema=None) as batch_op:
        batch_op.add_column(sa.Column('justificativa', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('exame_modelo', schema=None) as batch_op:
        batch_op.drop_column('justificativa')
