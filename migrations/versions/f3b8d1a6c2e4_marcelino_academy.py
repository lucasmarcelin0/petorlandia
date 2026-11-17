"""Marcelino Academy: curso de inglês como mini app.

Revision ID: f3b8d1a6c2e4
Revises: e2a7c4f9b1d3
Create Date: 2026-11-17 22:00:00.000000

Só cria tabelas novas (``academy_*``); nenhuma tabela existente é alterada.
"""
from alembic import op
import sqlalchemy as sa

revision = "f3b8d1a6c2e4"
down_revision = "e2a7c4f9b1d3"
branch_labels = None
depends_on = None

TABELAS = ["academy_comentario", "academy_resposta", "academy_opcao", "academy_questao",
           "academy_teste", "academy_licao", "academy_vinculo", "academy_materia"]


def _agora():
    return sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade():
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    if "academy_materia" in existentes:
        return

    op.create_table(
        "academy_materia",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("descricao", sa.Text()),
        sa.Column("link_aula", sa.String(300)),
        sa.Column("horario", sa.String(60)),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("criado_por", sa.String(160)),
        _agora(),
    )
    op.create_table(
        "academy_vinculo",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("materia_id", sa.Integer(), sa.ForeignKey("academy_materia.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False, index=True),
        sa.Column("papel", sa.String(20), nullable=False),
        sa.Column("concedido_por", sa.String(160)),
        sa.Column("concedido_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revogado_em", sa.DateTime(timezone=True)),
        sa.Column("revogado_por", sa.String(160)),
    )
    op.create_table(
        "academy_licao",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("materia_id", sa.Integer(), sa.ForeignKey("academy_materia.id"), nullable=False, index=True),
        sa.Column("titulo", sa.String(150), nullable=False),
        sa.Column("conteudo", sa.Text()),
        sa.Column("link_video", sa.String(300)),
        sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("publicada", sa.Boolean(), nullable=False, server_default=sa.true()),
        _agora(),
    )
    op.create_table(
        "academy_teste",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("licao_id", sa.Integer(), sa.ForeignKey("academy_licao.id"), nullable=False, index=True),
        sa.Column("nome", sa.String(150), nullable=False),
        _agora(),
    )
    op.create_table(
        "academy_questao",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("teste_id", sa.Integer(), sa.ForeignKey("academy_teste.id"), nullable=False, index=True),
        sa.Column("enunciado", sa.Text(), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False, server_default="unica"),
        sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ativa", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "academy_opcao",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("questao_id", sa.Integer(), sa.ForeignKey("academy_questao.id"), nullable=False, index=True),
        sa.Column("texto", sa.String(300), nullable=False),
        sa.Column("correta", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "academy_resposta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("questao_id", sa.Integer(), sa.ForeignKey("academy_questao.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False, index=True),
        sa.Column("opcoes", sa.Text()),
        sa.Column("texto", sa.Text()),
        sa.Column("nota", sa.Integer()),
        sa.Column("observacao", sa.Text()),
        sa.Column("corrigida_por", sa.String(160)),
        sa.Column("corrigida_em", sa.DateTime(timezone=True)),
        _agora(),
        sa.UniqueConstraint("questao_id", "user_id", name="uq_academy_resposta_questao_user"),
    )
    op.create_table(
        "academy_comentario",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("licao_id", sa.Integer(), sa.ForeignKey("academy_licao.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        _agora(),
    )


def downgrade():
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    for tabela in TABELAS:
        if tabela in existentes:
            op.drop_table(tabela)
