"""add nome_comercial to apresentacao_medicamento

Revision ID: 7dd91845a619
Revises: 799152204a27
Create Date: 2026-06-16 12:00:00.000000

Adiciona a coluna nome_comercial (VARCHAR 150, nullable) à tabela
apresentacao_medicamento para permitir que uma apresentação seja associada
a um nome de produto comercial (ex: "Sec Lac" para metergolina da Agener).

Isso viabiliza a busca por nome comercial no autocomplete de medicamentos:
pesquisar "Sec Lac" mostra apenas as apresentações da Agener, enquanto
pesquisar "metergolina" exibe todas as apresentações.
"""

from alembic import op
import sqlalchemy as sa


revision = '7dd91845a619'
down_revision = '799152204a27'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'apresentacao_medicamento',
        sa.Column('nome_comercial', sa.String(150), nullable=True),
    )


def downgrade():
    op.drop_column('apresentacao_medicamento', 'nome_comercial')
