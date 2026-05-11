"""add crmv_estado column to veterinario table

Revision ID: 1a2b3c4d5e6f
Revises: f8e2a4b7c9d1
Create Date: 2026-05-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1a2b3c4d5e6f'
down_revision = 'f8e2a4b7c9d1'
branch_labels = None
depends_on = None


def upgrade():
    # Check if column already exists before adding
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column['name'] for column in inspector.get_columns('veterinario')}
    
    if 'crmv_estado' not in existing_columns:
        op.add_column('veterinario', sa.Column('crmv_estado', sa.String(length=2), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column['name'] for column in inspector.get_columns('veterinario')}
    
    if 'crmv_estado' in existing_columns:
        op.drop_column('veterinario', 'crmv_estado')
