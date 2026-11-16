"""Limpeza urbana: tipos de problema cadastráveis, perfis de acesso e recorte por tipo.

Revision ID: c3d9a7e2f4b6
Revises: b8e1c4d7f901
Create Date: 2026-11-16 12:00:00.000000

Tabelas novas e colunas opcionais. Os seis tipos de hoje entram com as mesmas
chaves, então as comunicações existentes continuam com o mesmo nome.
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d9a7e2f4b6"
down_revision = "b8e1c4d7f901"
branch_labels = None
depends_on = None

TIPOS = [
    ("lixo", "Lixo acumulado"),
    ("entulho", "Entulho"),
    ("moveis", "Móveis e objetos grandes"),
    ("galhos", "Galhos e poda"),
    ("canteiro", "Canteiro ou praça sem limpeza"),
    ("outro", "Outro"),
]


def upgrade():
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    if "limpeza_tipo" not in existentes:
        tabela = op.create_table(
            "limpeza_tipo",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("chave", sa.String(30), nullable=False, unique=True),
            sa.Column("rotulo", sa.String(80), nullable=False),
            sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("criado_por", sa.String(160)),
            sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.bulk_insert(tabela, [
            {"chave": chave, "rotulo": rotulo, "ordem": (999 if chave == "outro" else (i + 1) * 10),
             "ativo": True, "criado_por": "Sistema"}
            for i, (chave, rotulo) in enumerate(TIPOS)
        ])
    if "limpeza_perfil" not in existentes:
        op.create_table(
            "limpeza_perfil",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nome", sa.String(80), nullable=False),
            sa.Column("papeis", sa.String(60), nullable=False),
            sa.Column("tipos", sa.String(300)),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("criado_por", sa.String(160)),
            sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    colunas = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("limpeza_acesso")}
    if "tipos" not in colunas:
        op.add_column("limpeza_acesso", sa.Column("tipos", sa.String(300), nullable=True))
    if "perfil" not in colunas:
        op.add_column("limpeza_acesso", sa.Column("perfil", sa.String(80), nullable=True))
    with op.batch_alter_table("limpeza_solicitacao") as batch:
        batch.alter_column("categorias", existing_type=sa.String(120), type_=sa.String(300),
                           existing_nullable=False)


def downgrade():
    with op.batch_alter_table("limpeza_solicitacao") as batch:
        batch.alter_column("categorias", existing_type=sa.String(300), type_=sa.String(120),
                           existing_nullable=False)
    op.drop_column("limpeza_acesso", "perfil")
    op.drop_column("limpeza_acesso", "tipos")
    op.drop_table("limpeza_perfil")
    op.drop_table("limpeza_tipo")
