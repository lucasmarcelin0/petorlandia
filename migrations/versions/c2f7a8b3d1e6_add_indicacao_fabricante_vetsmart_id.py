"""add indicacao/fabricante/vetsmart_produto_id columns

Revision ID: c2f7a8b3d1e6
Revises: a9d3e7b1c2f4
Create Date: 2026-04-19

Estes campos suportam:
  - consolidar medicamentos por princípio ativo (Medicamento = PA)
  - apresentações com fabricante próprio (mesma "Prednisona" pode ter
    apresentações da LigVet, Animalia, etc.)
  - doses categorizadas por indicação clínica (Alergia, Imunossupressão,
    Dermatite atópica, ...), pra o calculador de dose poder sugerir a dose
    correta por contexto.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c2f7a8b3d1e6'
down_revision = 'a9d3e7b1c2f4'
branch_labels = None
depends_on = None


def upgrade():
    # apresentacao_medicamento: fabricante + vetsmart_produto_id
    with op.batch_alter_table('apresentacao_medicamento') as batch:
        batch.add_column(sa.Column('fabricante',          sa.String(length=150), nullable=True))
        batch.add_column(sa.Column('vetsmart_produto_id', sa.Integer(),          nullable=True))

    op.create_index(
        'ix_apresentacao_medicamento_vetsmart_produto_id',
        'apresentacao_medicamento',
        ['vetsmart_produto_id'],
    )

    # dose_medicamento: indicacao clínica
    with op.batch_alter_table('dose_medicamento') as batch:
        batch.add_column(sa.Column('indicacao', sa.String(length=120), nullable=True))

    op.create_index(
        'ix_dose_medicamento_indicacao',
        'dose_medicamento',
        ['indicacao'],
    )

    # medicamento: vetsmart_produto_id (produto canônico do PA no VetSmart)
    with op.batch_alter_table('medicamento') as batch:
        batch.add_column(sa.Column('vetsmart_produto_id', sa.Integer(), nullable=True))

    op.create_index(
        'ix_medicamento_vetsmart_produto_id',
        'medicamento',
        ['vetsmart_produto_id'],
    )


def downgrade():
    op.drop_index('ix_medicamento_vetsmart_produto_id', table_name='medicamento')
    with op.batch_alter_table('medicamento') as batch:
        batch.drop_column('vetsmart_produto_id')

    op.drop_index('ix_dose_medicamento_indicacao', table_name='dose_medicamento')
    with op.batch_alter_table('dose_medicamento') as batch:
        batch.drop_column('indicacao')

    op.drop_index(
        'ix_apresentacao_medicamento_vetsmart_produto_id',
        table_name='apresentacao_medicamento',
    )
    with op.batch_alter_table('apresentacao_medicamento') as batch:
        batch.drop_column('vetsmart_produto_id')
        batch.drop_column('fabricante')
