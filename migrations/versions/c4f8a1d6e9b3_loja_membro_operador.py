"""loja: equipe (operador do caixa e do dia a dia)

Revision ID: c4f8a1d6e9b3
Revises: a9d4f6b2c8e3
Create Date: 2026-11-01 15:30:00.000000

Tabela nova; nada muda nas existentes.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c4f8a1d6e9b3'
down_revision = 'a9d4f6b2c8e3'
branch_labels = None
depends_on = None


def upgrade():
    if 'loja_membro' in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        'loja_membro',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('ativo', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('desativado_em', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('casa_de_racao_id', 'user_id', name='uq_loja_membro'),
    )
    op.create_index(op.f('ix_loja_membro_casa_de_racao_id'), 'loja_membro', ['casa_de_racao_id'])
    op.create_index(op.f('ix_loja_membro_user_id'), 'loja_membro', ['user_id'])


def downgrade():
    if 'loja_membro' in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table('loja_membro')
