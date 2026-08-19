"""Add free-text observations to user.

Guarda tambem os enderecos anteriores do tutor: o modelo tem uma unica vaga de
endereco (User.endereco_id) e existe tutor com mais de um, com animais vivendo
em locais diferentes. Trocar o endereco sem registrar o antigo apagaria a
informacao.
"""

from alembic import op
import sqlalchemy as sa


revision = 'a7f1c2d5b83e'
down_revision = 'd3c8e4a9b7f1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('observacoes', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('user', 'observacoes')
