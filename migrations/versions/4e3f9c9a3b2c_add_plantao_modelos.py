"""add plantao modelos table

Revision ID: 4e3f9c9a3b2c
Revises: 1f8d8d4bd6e5
Create Date: 2025-07-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '4e3f9c9a3b2c'
down_revision = '1f8d8d4bd6e5'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return inspector.has_table(table_name)


def upgrade():
    if _table_exists('plantao_modelos'):
        return

    op.create_table(
        'plantao_modelos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('clinic_id', sa.Integer(), sa.ForeignKey('clinica.id'), nullable=False),
        sa.Column('nome', sa.String(length=80), nullable=False),
        sa.Column('hora_inicio', sa.Time(), nullable=True),
        sa.Column('duracao_horas', sa.Numeric(5, 2), nullable=False),
        sa.Column('medico_id', sa.Integer(), sa.ForeignKey('veterinario.id'), nullable=True),
        sa.Column('medico_nome', sa.String(length=150), nullable=True),
        sa.Column('medico_cnpj', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_plantao_modelos_clinic_id', 'plantao_modelos', ['clinic_id'])
    op.create_index('ix_plantao_modelos_medico_id', 'plantao_modelos', ['medico_id'])


def downgrade():
    if not _table_exists('plantao_modelos'):
        return

    op.drop_index('ix_plantao_modelos_medico_id', table_name='plantao_modelos')
    op.drop_index('ix_plantao_modelos_clinic_id', table_name='plantao_modelos')
    op.drop_table('plantao_modelos')
