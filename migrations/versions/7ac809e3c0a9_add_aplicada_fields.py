"""add aplicada fields to vacina

Revision ID: 7ac809e3c0a9
Revises: 93a8666ff562
Create Date: 2025-09-03 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7ac809e3c0a9'
down_revision = '93a8666ff562'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vacina') as batch_op:
        batch_op.alter_column('data', new_column_name='aplicada_em')
        batch_op.add_column(sa.Column('aplicada', sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table('vacina') as batch_op:
        batch_op.drop_column('aplicada')
        batch_op.alter_column('aplicada_em', new_column_name='data')
