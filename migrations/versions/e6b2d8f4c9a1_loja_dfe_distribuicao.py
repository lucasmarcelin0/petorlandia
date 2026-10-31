"""loja: notas de compra baixadas da SEFAZ (distribuição DF-e)

Revision ID: e6b2d8f4c9a1
Revises: d5a9c7e3b1f2
Create Date: 2026-10-31 21:00:00.000000

Somente tabelas novas. A consulta à SEFAZ só acontece para lojas com
certificado A1 e configuração fiscal; nada existente muda.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e6b2d8f4c9a1'
down_revision = 'd5a9c7e3b1f2'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    existing = _tables()

    if 'loja_dfe_controle' not in existing:
        op.create_table(
            'loja_dfe_controle',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
            sa.Column('ult_nsu', sa.String(length=15), nullable=False, server_default='000000000000000'),
            sa.Column('max_nsu', sa.String(length=15), nullable=True),
            sa.Column('ultima_consulta', sa.DateTime(timezone=True), nullable=True),
            sa.Column('proxima_consulta', sa.DateTime(timezone=True), nullable=True),
            sa.Column('ultimo_c_stat', sa.String(length=4), nullable=True),
            sa.Column('ultimo_x_motivo', sa.String(length=255), nullable=True),
            sa.Column('ciencia_automatica', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('casa_de_racao_id'),
        )

    if 'loja_dfe_documento' not in existing:
        op.create_table(
            'loja_dfe_documento',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
            sa.Column('chave', sa.String(length=44), nullable=False),
            sa.Column('nsu', sa.String(length=15), nullable=True),
            sa.Column('emitente_cnpj', sa.String(length=14), nullable=True),
            sa.Column('emitente_nome', sa.String(length=160), nullable=True),
            sa.Column('dh_emi', sa.String(length=32), nullable=True),
            sa.Column('valor', sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column('situacao', sa.String(length=1), nullable=True),
            sa.Column('protocolo', sa.String(length=20), nullable=True),
            sa.Column('xml_completo', sa.Text(), nullable=True),
            sa.Column('ciencia_em', sa.DateTime(timezone=True), nullable=True),
            sa.Column('entrada_id', sa.Integer(), nullable=True),
            sa.Column('erro', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['entrada_id'], ['loja_entrada_nota.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('casa_de_racao_id', 'chave', name='uq_loja_dfe_documento_chave'),
        )
        op.create_index(op.f('ix_loja_dfe_documento_casa_de_racao_id'), 'loja_dfe_documento', ['casa_de_racao_id'])


def downgrade():
    existing = _tables()
    for table in ('loja_dfe_documento', 'loja_dfe_controle'):
        if table in existing:
            op.drop_table(table)
