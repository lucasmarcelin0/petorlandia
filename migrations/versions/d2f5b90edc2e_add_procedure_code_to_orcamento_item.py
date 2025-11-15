"""add procedure_code to orcamento_item

Revision ID: d2f5b90edc2e
Revises: ('fa2b77d13374', 'c0d8d170b5a4')
Create Date: 2024-05-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2f5b90edc2e'
down_revision = ('fa2b77d13374', 'c0d8d170b5a4')
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orcamento_item', sa.Column('procedure_code', sa.String(length=64), nullable=True))


def downgrade():
    op.drop_column('orcamento_item', 'procedure_code')
