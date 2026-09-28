"""Entomologia: arquivos de campo enviados pela equipe e boletins públicos.

Revision ID: f1e7a3c9b2d4
Revises: e4b8d5f2a411
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1e7a3c9b2d4'
down_revision = 'e4b8d5f2a411'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('entomologia_importacao',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tipo', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('nome_arquivo', sa.String(200), nullable=False),
        sa.Column('titulo', sa.String(200)),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('inicio', sa.Date()), sa.Column('fim', sa.Date()),
        sa.Column('linhas', sa.Integer(), nullable=False),
        sa.Column('resumo_json', sa.Text()),
        sa.Column('dados_json', sa.Text(), nullable=False),
        sa.Column('responsavel', sa.String(160), nullable=False),
        sa.Column('ator', sa.String(160)),
        sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('confirmado_em', sa.DateTime(timezone=True)),
        sa.Column('desfeito_em', sa.DateTime(timezone=True)),
        sa.Column('desfeito_por', sa.String(160)))
    for field in ('tipo', 'status', 'sha256'):
        op.create_index(f'ix_entomologia_importacao_{field}', 'entomologia_importacao', [field])
    op.create_table('entomologia_publicacao',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('inicio', sa.Date(), nullable=False),
        sa.Column('fim', sa.Date(), nullable=False),
        sa.Column('dados_json', sa.Text(), nullable=False),
        sa.Column('mensagem', sa.Text()),
        sa.Column('contato', sa.String(300)),
        sa.Column('assinatura', sa.String(200)),
        sa.Column('responsavel', sa.String(160), nullable=False),
        sa.Column('ator', sa.String(160)),
        sa.Column('publicado_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('retirado_em', sa.DateTime(timezone=True)),
        sa.Column('retirado_por', sa.String(160)))
    op.create_index('ix_entomologia_publicacao_status', 'entomologia_publicacao', ['status'])


def downgrade():
    op.drop_index('ix_entomologia_publicacao_status', table_name='entomologia_publicacao')
    op.drop_table('entomologia_publicacao')
    for field in ('tipo', 'status', 'sha256'):
        op.drop_index(f'ix_entomologia_importacao_{field}', table_name='entomologia_importacao')
    op.drop_table('entomologia_importacao')
