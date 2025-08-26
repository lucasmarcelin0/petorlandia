"""add clinica_id to appointment

Revision ID: 2b3b6d9f4c1a
Revises: 4652ffa73330
Create Date: 2025-09-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2b3b6d9f4c1a'
down_revision = '4652ffa73330'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('appointment', sa.Column('clinica_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'appointment', 'clinica', ['clinica_id'], ['id'])


def downgrade():
    op.drop_constraint(None, 'appointment', type_='foreignkey')
    op.drop_column('appointment', 'clinica_id')
