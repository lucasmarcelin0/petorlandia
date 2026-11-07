"""SFA: passos da pesquisa no painel (projeto, TCLE e questionário)

Revision ID: f8b2c6d4e1a7
Revises: e7a3c9d5b1f4
Create Date: 2026-11-07 12:00:00.000000

Tabela nova com os três passos iniciais. Nada muda nos dados existentes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = 'f8b2c6d4e1a7'
down_revision = 'e7a3c9d5b1f4'
branch_labels = None
depends_on = None

PASSOS_INICIAIS = [
    (1, 'Projeto de pesquisa',
     'https://docs.google.com/document/d/1ULrp0zsN6kFzF5PPYZ_MV-oGHafvgykCZJmllYiJRXQ/edit'),
    (2, 'TCLE',
     'https://docs.google.com/document/d/16QWpcGndfrZQ5etqSpGg6YKfeo60Ur2W8EJfJJj0n9M/edit'),
    (3, 'Questionário T0, T7 e T30',
     'https://docs.google.com/document/d/1jmqZ4PFBERifveDijHNgn_sJNv4Rtfztik0tI0VpDaw/edit'),
]


def upgrade():
    if 'sfa_passo_pesquisa' in sa.inspect(op.get_bind()).get_table_names():
        return
    tabela = op.create_table(
        'sfa_passo_pesquisa',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ordem', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('titulo', sa.String(120), nullable=False),
        sa.Column('url', sa.String(500), nullable=False, server_default=''),
        sa.Column('concluido', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('concluido_em', sa.DateTime(timezone=True)),
        sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False),
    )
    agora = datetime.now(timezone.utc)
    op.bulk_insert(tabela, [
        {'ordem': ordem, 'titulo': titulo, 'url': url, 'concluido': False, 'atualizado_em': agora}
        for ordem, titulo, url in PASSOS_INICIAIS
    ])


def downgrade():
    op.drop_table('sfa_passo_pesquisa')
