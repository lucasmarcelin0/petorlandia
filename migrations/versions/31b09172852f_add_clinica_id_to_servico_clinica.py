"""add clinica_id to servico_clinica

Revision ID: 31b09172852f
Revises: 1b8f1e5ef0c1
Create Date: 2025-09-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '31b09172852f'
down_revision = '1b8f1e5ef0c1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('servico_clinica', sa.Column('clinica_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'servico_clinica', 'clinica', ['clinica_id'], ['id'])


def downgrade():
    op.drop_constraint(None, 'servico_clinica', type_='foreignkey')
    op.drop_column('servico_clinica', 'clinica_id')
