"""add aplicada fields to vacina

Revision ID: 762f0e69f93c
Revises: 93a8666ff562
Create Date: 2025-09-03 22:31:08.666721

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '762f0e69f93c'
down_revision = '93a8666ff562'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vacina', schema=None) as batch_op:
        batch_op.add_column(sa.Column('aplicada', sa.Boolean(), server_default='0', nullable=True))
        batch_op.add_column(sa.Column('aplicada_em', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('aplicada_por', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_vacina_aplicada_por_user', 'user', ['aplicada_por'], ['id'])


def downgrade():
    with op.batch_alter_table('vacina', schema=None) as batch_op:
        batch_op.drop_constraint('fk_vacina_aplicada_por_user', type_='foreignkey')
        batch_op.drop_column('aplicada_por')
        batch_op.drop_column('aplicada_em')
        batch_op.drop_column('aplicada')
