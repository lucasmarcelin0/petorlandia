"""add medicamento_favorito table

Revision ID: 7ddc4b706765
Revises: d1a3f7c2b9e8
Create Date: 2026-05-04 19:32:40.592001

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7ddc4b706765'
down_revision = 'd1a3f7c2b9e8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'medicamento_favorito',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('medicamento_id', sa.Integer(), nullable=False),
        sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['medicamento_id'], ['medicamento.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'medicamento_id', name='uq_fav_user_med'),
    )
    op.create_index('ix_medicamento_favorito_user_id', 'medicamento_favorito', ['user_id'], unique=False)


def downgrade():
    op.drop_index('ix_medicamento_favorito_user_id', table_name='medicamento_favorito')
    op.drop_table('medicamento_favorito')
