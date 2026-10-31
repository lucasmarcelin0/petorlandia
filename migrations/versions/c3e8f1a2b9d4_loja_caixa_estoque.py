"""loja: caixa (PDV), vendas de balcão e movimentos de estoque

Revision ID: c3e8f1a2b9d4
Revises: b7d4e2f9a1c3
Create Date: 2026-10-31 18:00:00.000000

Tabelas novas e uma coluna opcional (product.cest). Nada existente muda:
a loja online continua igual e o caixa usa o mesmo estoque dos produtos.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c3e8f1a2b9d4'
down_revision = 'b7d4e2f9a1c3'
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tables():
    return set(_inspector().get_table_names())


def _columns(table):
    return {col['name'] for col in _inspector().get_columns(table)}


def upgrade():
    if 'cest' not in _columns('product'):
        op.add_column('product', sa.Column('cest', sa.String(length=7), nullable=True))

    existing = _tables()

    if 'loja_caixa_sessao' not in existing:
        op.create_table(
            'loja_caixa_sessao',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(length=10), nullable=False, server_default='aberto'),
            sa.Column('valor_abertura', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
            sa.Column('aberto_por_id', sa.Integer(), nullable=True),
            sa.Column('aberto_em', sa.DateTime(timezone=True), nullable=False),
            sa.Column('valor_contado', sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column('valor_esperado', sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column('fechado_por_id', sa.Integer(), nullable=True),
            sa.Column('fechado_em', sa.DateTime(timezone=True), nullable=True),
            sa.Column('observacao', sa.String(length=255), nullable=True),
            sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['aberto_por_id'], ['user.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['fechado_por_id'], ['user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_loja_caixa_sessao_casa_de_racao_id'), 'loja_caixa_sessao', ['casa_de_racao_id'])
        op.create_index(op.f('ix_loja_caixa_sessao_status'), 'loja_caixa_sessao', ['status'])
        op.create_index(
            'uq_loja_caixa_sessao_aberta',
            'loja_caixa_sessao',
            ['casa_de_racao_id'],
            unique=True,
            postgresql_where=sa.text("status = 'aberto'"),
            sqlite_where=sa.text("status = 'aberto'"),
        )

    if 'loja_caixa_movimento' not in existing:
        op.create_table(
            'loja_caixa_movimento',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('sessao_id', sa.Integer(), nullable=False),
            sa.Column('tipo', sa.String(length=12), nullable=False),
            sa.Column('valor', sa.Numeric(precision=12, scale=2), nullable=False),
            sa.Column('motivo', sa.String(length=255), nullable=True),
            sa.Column('usuario_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['sessao_id'], ['loja_caixa_sessao.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['usuario_id'], ['user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_loja_caixa_movimento_sessao_id'), 'loja_caixa_movimento', ['sessao_id'])

    if 'loja_venda' not in existing:
        op.create_table(
            'loja_venda',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('chave_cliente', sa.String(length=40), nullable=True),
            sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
            sa.Column('sessao_id', sa.Integer(), nullable=True),
            sa.Column('status', sa.String(length=12), nullable=False, server_default='concluida'),
            sa.Column('subtotal', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
            sa.Column('desconto', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
            sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
            sa.Column('troco', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
            sa.Column('emitir_nfce', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('nfce_documento_id', sa.Integer(), nullable=True),
            sa.Column('nfce_erro', sa.String(length=255), nullable=True),
            sa.Column('cancel_motivo', sa.String(length=255), nullable=True),
            sa.Column('cancelada_em', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_by_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['sessao_id'], ['loja_caixa_sessao.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['nfce_documento_id'], ['nfce_documento.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('casa_de_racao_id', 'chave_cliente', name='uq_loja_venda_chave_cliente'),
        )
        op.create_index(op.f('ix_loja_venda_casa_de_racao_id'), 'loja_venda', ['casa_de_racao_id'])
        op.create_index(op.f('ix_loja_venda_sessao_id'), 'loja_venda', ['sessao_id'])
        op.create_index(op.f('ix_loja_venda_status'), 'loja_venda', ['status'])
        op.create_index(op.f('ix_loja_venda_nfce_documento_id'), 'loja_venda', ['nfce_documento_id'])

    if 'loja_venda_item' not in existing:
        op.create_table(
            'loja_venda_item',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('venda_id', sa.Integer(), nullable=False),
            sa.Column('product_id', sa.Integer(), nullable=True),
            sa.Column('variant_id', sa.Integer(), nullable=True),
            sa.Column('codigo', sa.String(length=60), nullable=False),
            sa.Column('descricao', sa.String(length=160), nullable=False),
            sa.Column('unidade', sa.String(length=6), nullable=False, server_default='UN'),
            sa.Column('quantidade', sa.Numeric(precision=12, scale=4), nullable=False),
            sa.Column('preco_unitario', sa.Numeric(precision=12, scale=4), nullable=False),
            sa.Column('desconto', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
            sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=False),
            sa.Column('gtin', sa.String(length=14), nullable=True),
            sa.Column('ncm', sa.String(length=10), nullable=True),
            sa.Column('cest', sa.String(length=7), nullable=True),
            sa.Column('cfop', sa.String(length=4), nullable=True),
            sa.Column('csosn', sa.String(length=3), nullable=True),
            sa.Column('origem', sa.String(length=1), nullable=True),
            sa.ForeignKeyConstraint(['venda_id'], ['loja_venda.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['variant_id'], ['product_variant.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_loja_venda_item_venda_id'), 'loja_venda_item', ['venda_id'])
        op.create_index(op.f('ix_loja_venda_item_product_id'), 'loja_venda_item', ['product_id'])

    if 'loja_venda_pagamento' not in existing:
        op.create_table(
            'loja_venda_pagamento',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('venda_id', sa.Integer(), nullable=False),
            sa.Column('t_pag', sa.String(length=2), nullable=False),
            sa.Column('valor', sa.Numeric(precision=12, scale=2), nullable=False),
            sa.Column('autorizacao', sa.String(length=40), nullable=True),
            sa.ForeignKeyConstraint(['venda_id'], ['loja_venda.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_loja_venda_pagamento_venda_id'), 'loja_venda_pagamento', ['venda_id'])

    if 'loja_estoque_movimento' not in existing:
        op.create_table(
            'loja_estoque_movimento',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
            sa.Column('product_id', sa.Integer(), nullable=False),
            sa.Column('variant_id', sa.Integer(), nullable=True),
            sa.Column('tipo', sa.String(length=24), nullable=False),
            sa.Column('quantidade', sa.Numeric(precision=12, scale=4), nullable=False),
            sa.Column('saldo_apos', sa.Numeric(precision=12, scale=4), nullable=True),
            sa.Column('custo_unitario', sa.Numeric(precision=12, scale=4), nullable=True),
            sa.Column('referencia_tipo', sa.String(length=24), nullable=True),
            sa.Column('referencia_id', sa.Integer(), nullable=True),
            sa.Column('observacao', sa.String(length=255), nullable=True),
            sa.Column('usuario_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['variant_id'], ['product_variant.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['usuario_id'], ['user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_loja_estoque_movimento_casa_de_racao_id'), 'loja_estoque_movimento', ['casa_de_racao_id'])
        op.create_index(op.f('ix_loja_estoque_movimento_product_id'), 'loja_estoque_movimento', ['product_id'])
        op.create_index(op.f('ix_loja_estoque_movimento_referencia_id'), 'loja_estoque_movimento', ['referencia_id'])


def downgrade():
    existing = _tables()
    for table in (
        'loja_estoque_movimento',
        'loja_venda_pagamento',
        'loja_venda_item',
        'loja_venda',
        'loja_caixa_movimento',
        'loja_caixa_sessao',
    ):
        if table in existing:
            op.drop_table(table)
    if 'cest' in _columns('product'):
        op.drop_column('product', 'cest')
