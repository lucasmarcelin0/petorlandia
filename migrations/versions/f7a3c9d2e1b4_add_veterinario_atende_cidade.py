"""add veterinario_atende_cidade (cobertura multi-cidade do veterinário)

Cria a tabela que registra as cidades atendidas por um profissional volante
(ex.: ultrassonografista que atende Belo Horizonte, Contagem e Brumadinho).

Revision ID: f7a3c9d2e1b4
Revises: 472cb32f374e
Create Date: 2026-06-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'f7a3c9d2e1b4'
down_revision = '472cb32f374e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'veterinario_atende_cidade',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('veterinario_id', sa.Integer(), nullable=False),
        sa.Column('cidade', sa.String(length=120), nullable=False),
        sa.Column('uf', sa.String(length=2), nullable=True),
        sa.ForeignKeyConstraint(
            ['veterinario_id'], ['veterinario.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('veterinario_id', 'cidade', name='uq_vet_atende_cidade'),
    )
    op.create_index(
        op.f('ix_veterinario_atende_cidade_veterinario_id'),
        'veterinario_atende_cidade',
        ['veterinario_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f('ix_veterinario_atende_cidade_veterinario_id'),
        table_name='veterinario_atende_cidade',
    )
    op.drop_table('veterinario_atende_cidade')
