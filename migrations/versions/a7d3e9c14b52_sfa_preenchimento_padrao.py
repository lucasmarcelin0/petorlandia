"""Dados de preenchimento salvos por usuário para a ficha SINAN (unidade, município, investigador)."""
from alembic import op
import sqlalchemy as sa

revision = 'a7d3e9c14b52'
down_revision = 'f2c7a9d41b3e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sfa_preenchimento_padrao',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('dados_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('sfa_preenchimento_padrao')
