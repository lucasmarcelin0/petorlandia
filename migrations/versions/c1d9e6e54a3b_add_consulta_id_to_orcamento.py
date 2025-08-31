"""add consulta_id to orcamento

Revision ID: c1d9e6e54a3b
Revises: 9d3d3cdb1de4
Create Date: 2025-10-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c1d9e6e54a3b'
down_revision = '9d3d3cdb1de4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orcamento', sa.Column('consulta_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'orcamento', 'consulta', ['consulta_id'], ['id'])


def downgrade():
    op.drop_constraint(None, 'orcamento', type_='foreignkey')
    op.drop_column('orcamento', 'consulta_id')
