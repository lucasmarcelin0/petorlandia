"""add prescricao_alias_medicamento table

Revision ID: b8f2e1d3c9a7
Revises: c6c8c78ce463
Create Date: 2026-05-04 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b8f2e1d3c9a7'
down_revision = 'c6c8c78ce463'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'prescricao_alias_medicamento',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome_prescrito', sa.Text(), nullable=False),
        sa.Column('medicamento_id', sa.Integer(), nullable=True),
        sa.Column('confianca', sa.String(20), nullable=False, server_default='auto'),
        sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['medicamento_id'], ['medicamento.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nome_prescrito', name='uq_alias_nome_prescrito'),
    )
    op.create_index('ix_alias_medicamento_id', 'prescricao_alias_medicamento', ['medicamento_id'])


def downgrade():
    op.drop_index('ix_alias_medicamento_id', table_name='prescricao_alias_medicamento')
    op.drop_table('prescricao_alias_medicamento')
