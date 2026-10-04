"""Artefatos do atlas pré-calculados (índice de busca e geometrias), por versão dos dados.

Tabela nova e isolada: nada existente muda. O conteúdo é derivado e refeito
sozinho pelo scheduler; a reversão só descarta essa cópia.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7d3c1e9f4b2'
down_revision = 'f2c7a9d41b3e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('entomologia_atlas_artefato',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('versao', sa.String(32), nullable=False),
        sa.Column('variante', sa.String(16), nullable=False),
        sa.Column('tipo', sa.String(24), nullable=False),
        sa.Column('corpo', sa.LargeBinary(), nullable=False),
        sa.Column('corpo_br', sa.LargeBinary(), nullable=True),
        sa.Column('etag', sa.String(40), nullable=False),
        sa.Column('bytes_crus', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('versao', 'variante', 'tipo', name='uq_entomologia_atlas_artefato'))
    op.create_index('ix_entomologia_atlas_artefato_versao', 'entomologia_atlas_artefato', ['versao'])


def downgrade():
    op.drop_index('ix_entomologia_atlas_artefato_versao', table_name='entomologia_atlas_artefato')
    op.drop_table('entomologia_atlas_artefato')
