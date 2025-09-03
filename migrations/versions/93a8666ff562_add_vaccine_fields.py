"""add vaccine fields

Revision ID: 93a8666ff562
Revises: d3f98e045e2b
Create Date: 2025-09-03 15:53:25.992133

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '93a8666ff562'
down_revision = 'd3f98e045e2b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vacina_modelo') as batch_op:
        batch_op.add_column(sa.Column('fabricante', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('doses_totais', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('intervalo_dias', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('frequencia', sa.String(length=50), nullable=True))

    with op.batch_alter_table('vacina') as batch_op:
        batch_op.add_column(sa.Column('fabricante', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('doses_totais', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('intervalo_dias', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('frequencia', sa.String(length=50), nullable=True))


def downgrade():
    with op.batch_alter_table('vacina') as batch_op:
        batch_op.drop_column('frequencia')
        batch_op.drop_column('intervalo_dias')
        batch_op.drop_column('doses_totais')
        batch_op.drop_column('fabricante')

    with op.batch_alter_table('vacina_modelo') as batch_op:
        batch_op.drop_column('frequencia')
        batch_op.drop_column('intervalo_dias')
        batch_op.drop_column('doses_totais')
        batch_op.drop_column('fabricante')
