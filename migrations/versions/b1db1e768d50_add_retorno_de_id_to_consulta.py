"""add retorno_de_id to consulta"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b1db1e768d50'
down_revision = 'ffcc9c32861f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('consulta', sa.Column('retorno_de_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'consulta', 'consulta', ['retorno_de_id'], ['id'])


def downgrade():
    op.drop_constraint(None, 'consulta', type_='foreignkey')
    op.drop_column('consulta', 'retorno_de_id')
