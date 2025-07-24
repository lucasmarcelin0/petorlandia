"""Add ProductPhoto table"""
from alembic import op
import sqlalchemy as sa

revision = '59ba2d1f5928'
down_revision = 'e8aff173e0fe'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'product_photo',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('product.id'), nullable=False),
        sa.Column('image_url', sa.String(length=200), nullable=True)
    )


def downgrade():
    op.drop_table('product_photo')
