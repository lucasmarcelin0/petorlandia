"""loja: entrada de mercadoria pelo XML da NF-e de compra

Revision ID: d5a9c7e3b1f2
Revises: c3e8f1a2b9d4
Create Date: 2026-10-31 20:00:00.000000

Tabelas novas e uma coluna opcional (product_variant.custo). Nada existente
muda: a entrada só mexe no estoque quando a loja confere e lança a nota.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd5a9c7e3b1f2'
down_revision = 'c3e8f1a2b9d4'
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tables():
    return set(_inspector().get_table_names())


def _columns(table):
    return {col['name'] for col in _inspector().get_columns(table)}


def upgrade():
    if 'custo' not in _columns('product_variant'):
        op.add_column('product_variant', sa.Column('custo', sa.Numeric(precision=12, scale=4), nullable=True))

    existing = _tables()

    if 'loja_entrada_nota' not in existing:
        op.create_table(
            'loja_entrada_nota',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
            sa.Column('chave', sa.String(length=44), nullable=False),
            sa.Column('numero', sa.String(length=9), nullable=True),
            sa.Column('serie', sa.String(length=3), nullable=True),
            sa.Column('dh_emi', sa.String(length=32), nullable=True),
            sa.Column('fornecedor_cnpj', sa.String(length=14), nullable=True),
            sa.Column('fornecedor_nome', sa.String(length=160), nullable=True),
            sa.Column('valor_total', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
            sa.Column('protocolo', sa.String(length=20), nullable=True),
            sa.Column('autorizada', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('origem', sa.String(length=12), nullable=False, server_default='upload'),
            sa.Column('status', sa.String(length=12), nullable=False, server_default='rascunho'),
            sa.Column('xml', sa.Text(), nullable=True),
            sa.Column('created_by_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('lancada_em', sa.DateTime(timezone=True), nullable=True),
            sa.Column('lancada_por_id', sa.Integer(), nullable=True),
            sa.Column('estornada_em', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['lancada_por_id'], ['user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('casa_de_racao_id', 'chave', name='uq_loja_entrada_nota_chave'),
        )
        op.create_index(op.f('ix_loja_entrada_nota_casa_de_racao_id'), 'loja_entrada_nota', ['casa_de_racao_id'])
        op.create_index(op.f('ix_loja_entrada_nota_fornecedor_cnpj'), 'loja_entrada_nota', ['fornecedor_cnpj'])
        op.create_index(op.f('ix_loja_entrada_nota_status'), 'loja_entrada_nota', ['status'])

    if 'loja_entrada_item' not in existing:
        op.create_table(
            'loja_entrada_item',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('entrada_id', sa.Integer(), nullable=False),
            sa.Column('n_item', sa.Integer(), nullable=False),
            sa.Column('codigo_fornecedor', sa.String(length=60), nullable=False),
            sa.Column('descricao', sa.String(length=160), nullable=False),
            sa.Column('gtin', sa.String(length=14), nullable=True),
            sa.Column('gtin_trib', sa.String(length=14), nullable=True),
            sa.Column('ncm', sa.String(length=8), nullable=True),
            sa.Column('cest', sa.String(length=7), nullable=True),
            sa.Column('origem', sa.String(length=1), nullable=True),
            sa.Column('unidade_compra', sa.String(length=6), nullable=False, server_default='UN'),
            sa.Column('quantidade_compra', sa.Numeric(precision=14, scale=4), nullable=False),
            sa.Column('valor_total', sa.Numeric(precision=12, scale=2), nullable=False),
            sa.Column('acao', sa.String(length=10), nullable=False, server_default='criar'),
            sa.Column('fator', sa.Numeric(precision=12, scale=4), nullable=False, server_default='1'),
            sa.Column('product_id', sa.Integer(), nullable=True),
            sa.Column('variant_id', sa.Integer(), nullable=True),
            sa.Column('preco_venda', sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column('unidade_venda', sa.String(length=6), nullable=True),
            sa.Column('sugestao', sa.String(length=20), nullable=True),
            sa.ForeignKeyConstraint(['entrada_id'], ['loja_entrada_nota.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['variant_id'], ['product_variant.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_loja_entrada_item_entrada_id'), 'loja_entrada_item', ['entrada_id'])

    if 'loja_fornecedor_produto' not in existing:
        op.create_table(
            'loja_fornecedor_produto',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
            sa.Column('fornecedor_cnpj', sa.String(length=14), nullable=False),
            sa.Column('codigo_fornecedor', sa.String(length=60), nullable=False),
            sa.Column('product_id', sa.Integer(), nullable=False),
            sa.Column('variant_id', sa.Integer(), nullable=True),
            sa.Column('fator', sa.Numeric(precision=12, scale=4), nullable=False, server_default='1'),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['variant_id'], ['product_variant.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint(
                'casa_de_racao_id', 'fornecedor_cnpj', 'codigo_fornecedor', name='uq_loja_fornecedor_produto'
            ),
        )
        op.create_index(op.f('ix_loja_fornecedor_produto_casa_de_racao_id'), 'loja_fornecedor_produto', ['casa_de_racao_id'])


def downgrade():
    existing = _tables()
    for table in ('loja_fornecedor_produto', 'loja_entrada_item', 'loja_entrada_nota'):
        if table in existing:
            op.drop_table(table)
    if 'custo' in _columns('product_variant'):
        op.drop_column('product_variant', 'custo')
