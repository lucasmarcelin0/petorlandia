"""improving mercado pago integration

Revision ID: 07c9382e9aad
Revises: 6ec5a8a3dea4
Create Date: 2025-07-27 23:07:29.829938

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '07c9382e9aad'
down_revision = '6ec5a8a3dea4'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mp_category_id', sa.String(length=50), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.drop_column('mp_category_id')

    # ### end Alembic commands ###
