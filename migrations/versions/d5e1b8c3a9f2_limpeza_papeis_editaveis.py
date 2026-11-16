"""Limpeza urbana: papéis criados e editados pelo administrador.

Revision ID: d5e1b8c3a9f2
Revises: c3d9a7e2f4b6
Create Date: 2026-11-16 14:00:00.000000

Os três papéis de hoje viram linhas editáveis com as mesmas chaves (os
acessos atuais não mudam). Perfis salvos viram papéis, e os acessos dados
por um perfil passam para o papel correspondente.
"""
import re
import unicodedata

from alembic import op
import sqlalchemy as sa

revision = "d5e1b8c3a9f2"
down_revision = "c3d9a7e2f4b6"
branch_labels = None
depends_on = None

PADRAO = [
    ("colaborador", "Colaborador", "comunicar"),
    ("equipe", "Equipe de limpeza", "comunicar,mapa,comprovar"),
    ("fiscal", "Fiscalização", "comunicar,mapa,recusar,descartar,exportar"),
]
ORDEM = ["comunicar", "mapa", "comprovar", "recusar", "descartar", "exportar"]


def _chave(nome, usadas):
    texto = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    base = "-".join(re.sub(r"[^a-z0-9]+", " ", texto).split())[:20].strip("-") or "papel"
    chave, n = base, 2
    while chave in usadas:
        chave, n = f"{base[:17]}-{n}", n + 1
    usadas.add(chave)
    return chave


def upgrade():
    bind = op.get_bind()
    if "limpeza_papel" in sa.inspect(bind).get_table_names():
        return
    tabela = op.create_table(
        "limpeza_papel",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chave", sa.String(20), nullable=False, unique=True),
        sa.Column("nome", sa.String(80), nullable=False),
        sa.Column("permissoes", sa.String(120), nullable=False),
        sa.Column("tipos", sa.String(300)),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("criado_por", sa.String(160)),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    linhas = [{"chave": c, "nome": n, "permissoes": p, "tipos": None, "ativo": True, "criado_por": "Sistema"}
              for c, n, p in PADRAO]
    usadas = {c for c, _, _ in PADRAO}
    nomes = {n.lower() for _, n, _ in PADRAO}
    perms_padrao = {c: set(p.split(",")) for c, _, p in PADRAO}
    convertidos = []
    for nome, papeis, tipos in bind.execute(sa.text(
            "SELECT nome, papeis, tipos FROM limpeza_perfil WHERE ativo")).fetchall():
        if not nome or nome.lower() in nomes:
            continue
        perms = set()
        for papel in (papeis or "").split(","):
            perms |= perms_padrao.get(papel, set())
        if not perms:
            continue
        chave = _chave(nome, usadas)
        nomes.add(nome.lower())
        linhas.append({"chave": chave, "nome": nome, "permissoes": ",".join(p for p in ORDEM if p in perms),
                       "tipos": tipos or None, "ativo": True, "criado_por": "Perfil salvo"})
        convertidos.append((nome, chave))
    op.bulk_insert(tabela, linhas)
    for nome, chave in convertidos:
        bind.execute(sa.text("UPDATE limpeza_acesso SET papel = :chave WHERE perfil = :nome AND revogado_em IS NULL"),
                     {"chave": chave, "nome": nome})


def downgrade():
    op.drop_table("limpeza_papel")
