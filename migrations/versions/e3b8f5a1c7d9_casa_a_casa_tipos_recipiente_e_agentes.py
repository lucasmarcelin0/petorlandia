"""casa a casa: recipientes por tipo e os dois primeiros agentes na equipe

Revision ID: e3b8f5a1c7d9
Revises: d9a4c1e7b352
Create Date: 2026-10-14 08:30:00.000000

Acrescenta à visita a lista de recipientes por tipo (1 a 40, ficha do SISAWEB).
A coluna é opcional: visitas antigas e aparelhos ainda na versão anterior
seguem só com os totais.

Também põe na equipe "Combate à dengue" as duas contas que vão trabalhar o
casa a casa por enquanto, para aparecerem no plano do dia e poderem registrar.
Só age em conta que existe e ainda não tem vínculo ativo; o vínculo aparece no
painel da equipe e pode ser revogado lá como qualquer outro.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e3b8f5a1c7d9'
down_revision = 'd9a4c1e7b352'
branch_labels = None
depends_on = None

AGENTES = ('lukemarki3@gmail.com', 'cvorlandia@gmail.com')
CONCEDIDO_POR = 'Casa a casa: agentes iniciais'


def upgrade():
    op.add_column('entomologia_visita_domiciliar', sa.Column('recipientes_json', sa.Text(), nullable=True))

    conexao = op.get_bind()
    usuario = sa.table('user', sa.column('id', sa.Integer), sa.column('email', sa.String))
    equipe = sa.table('entomologia_equipe', sa.column('user_id', sa.Integer), sa.column('concedido_por', sa.String),
                      sa.column('concedido_em', sa.DateTime(timezone=True)),
                      sa.column('revogado_em', sa.DateTime(timezone=True)))
    for email in AGENTES:
        user_id = conexao.execute(sa.select(usuario.c.id).where(sa.func.lower(usuario.c.email) == email)
                                  .order_by(usuario.c.id).limit(1)).scalar()
        if user_id is None:
            continue
        ativo = conexao.execute(sa.select(equipe.c.user_id).where(equipe.c.user_id == user_id,
                                                                  equipe.c.revogado_em.is_(None)).limit(1)).first()
        if ativo is None:
            conexao.execute(equipe.insert().values(user_id=user_id, concedido_por=CONCEDIDO_POR,
                                                   concedido_em=sa.func.now()))


def downgrade():
    # O vínculo na equipe fica: revogar acesso é decisão do painel, não de uma volta de versão.
    op.drop_column('entomologia_visita_domiciliar', 'recipientes_json')
