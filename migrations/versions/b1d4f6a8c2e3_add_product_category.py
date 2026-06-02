"""add product category column and manageable category table

Revision ID: b1d4f6a8c2e3
Revises: a5c7e9d2f4b8
Create Date: 2026-06-02 00:00:00.000000

Aditiva e não destrutiva:
  - adiciona a coluna ``product.category`` (NULL para os produtos existentes);
  - cria a tabela ``product_category`` (categorias gerenciáveis pelo admin);
  - semeia as categorias iniciais.
Nenhum dado existente é alterado ou removido.
"""

from alembic import op
import sqlalchemy as sa


revision = 'b1d4f6a8c2e3'
down_revision = 'a5c7e9d2f4b8'
branch_labels = None
depends_on = None


SEED_CATEGORIES = [
    {"slug": "racao",       "label": "Ração",            "icon": "fa-bowl-food", "position": 0},
    {"slug": "petisco",     "label": "Petiscos",         "icon": "fa-bone",      "position": 1},
    {"slug": "brinquedo",   "label": "Brinquedos",       "icon": "fa-baseball",  "position": 2},
    {"slug": "higiene",     "label": "Higiene & Beleza", "icon": "fa-pump-soap", "position": 3},
    {"slug": "acessorio",   "label": "Acessórios",       "icon": "fa-tag",       "position": 4},
    {"slug": "medicamento", "label": "Medicamentos",     "icon": "fa-pills",     "position": 5},
]


def upgrade():
    # 1) Coluna de categoria no produto (usada pelos filtros e pelo badge).
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category', sa.String(length=40), nullable=True))
        batch_op.create_index('ix_product_category', ['category'], unique=False)

    # 2) Tabela de categorias gerenciáveis pelo admin.
    product_category = op.create_table(
        'product_category',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=40), nullable=False),
        sa.Column('label', sa.String(length=60), nullable=False),
        sa.Column('icon', sa.String(length=40), nullable=True),
        sa.Column('position', sa.Integer(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug', name='uq_product_category_slug'),
    )

    # 3) Semente com as categorias iniciais.
    op.bulk_insert(product_category, [dict(c, active=True) for c in SEED_CATEGORIES])


def downgrade():
    op.drop_table('product_category')
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.drop_index('ix_product_category')
        batch_op.drop_column('category')
