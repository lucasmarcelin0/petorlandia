"""add specialty model

Revision ID: b5c3f2d1e0ab
Revises: 01fb1a503d86
Create Date: 2024-11-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b5c3f2d1e0ab'
down_revision = '01fb1a503d86'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'specialty',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nome')
    )
    op.create_table(
        'veterinario_especialidade',
        sa.Column('veterinario_id', sa.Integer(), nullable=False),
        sa.Column('specialty_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['veterinario_id'], ['veterinario.id']),
        sa.ForeignKeyConstraint(['specialty_id'], ['specialty.id']),
        sa.PrimaryKeyConstraint('veterinario_id', 'specialty_id')
    )

def downgrade():
    op.drop_table('veterinario_especialidade')
    op.drop_table('specialty')
