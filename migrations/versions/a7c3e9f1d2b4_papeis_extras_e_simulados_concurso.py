"""Papéis adicionais do usuário e simulados de concurso.

Revision ID: a7c3e9f1d2b4
Revises: a6c2e9d4b7f1
Create Date: 2026-11-18 10:00:00.000000

``user`` ganha duas colunas anuláveis (``roles_extras``, ``workers_extras``),
sem tocar nos valores existentes. Os simulados só criam tabelas novas.
"""
from alembic import op
import sqlalchemy as sa

revision = "a7c3e9f1d2b4"
down_revision = "a6c2e9d4b7f1"
branch_labels = None
depends_on = None


def upgrade():
    inspetor = sa.inspect(op.get_bind())
    colunas = {c["name"] for c in inspetor.get_columns("user")}
    with op.batch_alter_table("user") as batch:
        if "roles_extras" not in colunas:
            batch.add_column(sa.Column("roles_extras", sa.String(255), nullable=True))
        if "workers_extras" not in colunas:
            batch.add_column(sa.Column("workers_extras", sa.String(255), nullable=True))

    tabelas = set(inspetor.get_table_names())
    if "concurso_prova" not in tabelas:
        op.create_table(
            "concurso_prova",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("titulo", sa.String(200), nullable=False),
            sa.Column("banca", sa.String(80)),
            sa.Column("cargo", sa.String(120)),
            sa.Column("ano", sa.Integer()),
            sa.Column("total_questoes", sa.Integer(), nullable=False),
            sa.Column("gabarito", sa.String(400), nullable=False),
            sa.Column("pdf_nome", sa.String(200)),
            sa.Column("pdf_prova", sa.LargeBinary()),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("criado_por_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
            sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    if "concurso_tentativa" not in tabelas:
        op.create_table(
            "concurso_tentativa",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("prova_id", sa.Integer(), sa.ForeignKey("concurso_prova.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("respostas", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("iniciada_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("atualizada_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("entregue_em", sa.DateTime(timezone=True)),
            sa.Column("acertos", sa.Integer()),
        )
        op.create_index("ix_concurso_tentativa_prova_id", "concurso_tentativa", ["prova_id"])
        op.create_index("ix_concurso_tentativa_user_id", "concurso_tentativa", ["user_id"])


def downgrade():
    op.drop_table("concurso_tentativa")
    op.drop_table("concurso_prova")
    with op.batch_alter_table("user") as batch:
        batch.drop_column("workers_extras")
        batch.drop_column("roles_extras")
