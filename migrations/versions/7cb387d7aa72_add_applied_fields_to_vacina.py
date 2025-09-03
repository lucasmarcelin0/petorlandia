"""add applied fields to vacina

Revision ID: 7cb387d7aa72
Revises: 93a8666ff562
Create Date: 2024-05-28 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7cb387d7aa72'
down_revision = '93a8666ff562'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vacina') as batch_op:
        batch_op.add_column(sa.Column('aplicada', sa.Boolean(), nullable=True, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('aplicada_em', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('aplicada_por', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_vacina_aplicada_por_user', 'user', ['aplicada_por'], ['id'], ondelete='SET NULL')
    with op.batch_alter_table('vacina') as batch_op:
        batch_op.alter_column('aplicada', server_default=None)


def downgrade():
    with op.batch_alter_table('vacina') as batch_op:
        batch_op.drop_constraint('fk_vacina_aplicada_por_user', type_='foreignkey')
        batch_op.drop_column('aplicada_por')
        batch_op.drop_column('aplicada_em')
        batch_op.drop_column('aplicada')
