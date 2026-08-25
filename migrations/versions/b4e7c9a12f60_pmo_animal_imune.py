"""Registra o animal que nao precisou de dose por ja estar imunizado.

A antirrabica e anual e a mesma casa volta para a lista em encaixes e
remarcacoes. Ate aqui o vacinador so tinha "vacinado" para fechar o animal, e
esse status e o que conta dose gasta e alimenta a cobertura da campanha.
Marcar como vacinado quem nao recebeu nada inflaria o consumo de doses e ainda
adiantaria o relogio da protecao em um ano.

A coluna guarda a data da dose anterior que justificou pular a aplicacao, para
que a decisao fique auditavel. O status novo ("imunizado") nao muda schema: a
coluna status ja e texto livre validado na aplicacao.
"""

from alembic import op
import sqlalchemy as sa


revision = 'b4e7c9a12f60'
down_revision = 'a7f1c2d5b83e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'pmo_vaccination_animal',
        sa.Column('immune_since', sa.Date(), nullable=True),
    )


def downgrade():
    op.drop_column('pmo_vaccination_animal', 'immune_since')
