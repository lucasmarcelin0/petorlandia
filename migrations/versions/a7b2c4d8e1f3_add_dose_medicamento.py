"""add dose_medicamento table

Revision ID: a7b2c4d8e1f3
Revises: 11319daa4cf1
Create Date: 2026-04-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7b2c4d8e1f3'
down_revision = '11319daa4cf1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'dose_medicamento',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('medicamento_id', sa.Integer(), nullable=False),
        sa.Column('especie', sa.String(length=80), nullable=True),
        sa.Column('faixa_peso', sa.String(length=80), nullable=True),
        sa.Column('via', sa.String(length=80), nullable=True),
        sa.Column('dose', sa.String(length=200), nullable=True),
        sa.Column('frequencia', sa.String(length=120), nullable=True),
        sa.Column('duracao', sa.String(length=120), nullable=True),
        sa.Column('observacao', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['medicamento_id'], ['medicamento.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_dose_medicamento_medicamento_id',
        'dose_medicamento',
        ['medicamento_id'],
        unique=False,
    )


def downgrade():
    op.drop_index('ix_dose_medicamento_medicamento_id', table_name='dose_medicamento')
    op.drop_table('dose_medicamento')
