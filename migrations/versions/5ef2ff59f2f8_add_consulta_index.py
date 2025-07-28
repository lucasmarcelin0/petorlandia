"""add consulta index

Revision ID: 5ef2ff59f2f8
Revises: 07c9382e9aad
Create Date: 2025-07-28 22:08:24.382673

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5ef2ff59f2f8'
down_revision = '07c9382e9aad'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_consulta_animal_status',
        'consulta',
        ['animal_id', 'status']
    )


def downgrade():
    op.drop_index('ix_consulta_animal_status', table_name='consulta')
