"""add product variants

Revision ID: fdd4c2a9b8e1
Revises: fc1d7a9e4b2c
Create Date: 2026-07-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'fdd4c2a9b8e1'
down_revision = 'fc1d7a9e4b2c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'product_variant',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('dosage', sa.String(length=80), nullable=True),
        sa.Column('package_quantity', sa.String(length=80), nullable=True),
        sa.Column('weight_volume', sa.String(length=80), nullable=True),
        sa.Column('sku', sa.String(length=80), nullable=True),
        sa.Column('barcode', sa.String(length=80), nullable=True),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('stock', sa.Integer(), nullable=True),
        sa.Column('image_url', sa.String(length=200), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_product_variant_product_id'), 'product_variant', ['product_id'], unique=False)
    op.add_column('order_item', sa.Column('variant_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_order_item_variant_id'), 'order_item', ['variant_id'], unique=False)
    op.create_foreign_key(
        'fk_order_item_product_variant',
        'order_item',
        'product_variant',
        ['variant_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # Backfill: cada Product legado passa a ter uma variação padrão.
    op.execute(
        """
        INSERT INTO product_variant
            (product_id, name, price, stock, status, position)
        SELECT id, 'Padrão', price, stock, 'active', 0
        FROM product
        WHERE NOT EXISTS (
            SELECT 1 FROM product_variant pv WHERE pv.product_id = product.id
        )
        """
    )


def downgrade():
    op.drop_constraint('fk_order_item_product_variant', 'order_item', type_='foreignkey')
    op.drop_index(op.f('ix_order_item_variant_id'), table_name='order_item')
    op.drop_column('order_item', 'variant_id')
    op.drop_index(op.f('ix_product_variant_product_id'), table_name='product_variant')
    op.drop_table('product_variant')
