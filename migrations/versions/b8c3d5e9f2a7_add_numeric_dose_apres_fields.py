"""add numeric dose + apres fields for dose calculator

Revision ID: b8c3d5e9f2a7
Revises: a7b2c4d8e1f3
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = 'b8c3d5e9f2a7'
down_revision = 'a7b2c4d8e1f3'
branch_labels = None
depends_on = None


def upgrade():
    # apresentacao_medicamento
    with op.batch_alter_table('apresentacao_medicamento') as batch:
        batch.add_column(sa.Column('nome_variante',        sa.String(length=100), nullable=True))
        batch.add_column(sa.Column('concentracao_valor',   sa.Numeric(12, 3),     nullable=True))
        batch.add_column(sa.Column('concentracao_unidade', sa.String(length=20),  nullable=True))
        batch.add_column(sa.Column('volume_valor',         sa.Numeric(12, 3),     nullable=True))
        batch.add_column(sa.Column('volume_unidade',       sa.String(length=20),  nullable=True))

    # dose_medicamento
    with op.batch_alter_table('dose_medicamento') as batch:
        batch.add_column(sa.Column('especie_code',       sa.String(length=10),  nullable=True))
        batch.add_column(sa.Column('peso_min_kg',        sa.Numeric(8, 2),      nullable=True))
        batch.add_column(sa.Column('peso_max_kg',        sa.Numeric(8, 2),      nullable=True))
        batch.add_column(sa.Column('dose_min',           sa.Numeric(12, 3),     nullable=True))
        batch.add_column(sa.Column('dose_max',           sa.Numeric(12, 3),     nullable=True))
        batch.add_column(sa.Column('dose_unidade',       sa.String(length=30),  nullable=True))
        batch.add_column(sa.Column('intervalo_horas',    sa.Integer(),          nullable=True))
        batch.add_column(sa.Column('duracao_min_dias',   sa.Integer(),          nullable=True))
        batch.add_column(sa.Column('duracao_max_dias',   sa.Integer(),          nullable=True))
        batch.add_column(sa.Column('dose_raw_text',      sa.Text(),             nullable=True))
        batch.add_column(sa.Column('fonte',              sa.String(length=15),  nullable=True, server_default='HUMANO'))
        batch.add_column(sa.Column('confianca',          sa.String(length=10),  nullable=True, server_default='MEDIA'))

    op.create_index('ix_dose_medicamento_especie_code', 'dose_medicamento', ['especie_code'])


def downgrade():
    op.drop_index('ix_dose_medicamento_especie_code', table_name='dose_medicamento')
    with op.batch_alter_table('dose_medicamento') as batch:
        for col in ['confianca','fonte','dose_raw_text','duracao_max_dias','duracao_min_dias',
                    'intervalo_horas','dose_unidade','dose_max','dose_min',
                    'peso_max_kg','peso_min_kg','especie_code']:
            batch.drop_column(col)
    with op.batch_alter_table('apresentacao_medicamento') as batch:
        for col in ['volume_unidade','volume_valor','concentracao_unidade','concentracao_valor','nome_variante']:
            batch.drop_column(col)
