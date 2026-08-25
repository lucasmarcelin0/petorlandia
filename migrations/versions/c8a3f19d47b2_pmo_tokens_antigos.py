"""Guarda os links de carteirinha que ja foram entregues ao morador.

O public_token da visita muda quando o registro e recriado -- por exemplo
quando a linha muda de lugar na planilha e o sync apaga e recria a visita. O
tutor, porem, ja recebeu o link antigo por WhatsApp, com a marca da
Prefeitura. Um link publicado assim nao pode virar 404.

Esta tabela guarda cada token ja usado por uma visita. A busca da carteirinha
tenta o token atual e, se nao achar, cai aqui.
"""

from alembic import op
import sqlalchemy as sa


revision = 'c8a3f19d47b2'
down_revision = 'b4e7c9a12f60'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pmo_vaccination_visit_token',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('visit_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=96), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['visit_id'], ['pmo_vaccination_visit.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_pmo_visit_token'),
    )
    op.create_index('ix_pmo_visit_token_visit', 'pmo_vaccination_visit_token',
                    ['visit_id'])

    # Todo token vigente entra no historico: a partir de agora, qualquer link
    # ja entregue continua valendo mesmo se a visita for recriada.
    op.execute(
        """
        INSERT INTO pmo_vaccination_visit_token (visit_id, token)
        SELECT id, public_token
        FROM pmo_vaccination_visit
        WHERE public_token IS NOT NULL
        """
    )


def downgrade():
    op.drop_index('ix_pmo_visit_token_visit', table_name='pmo_vaccination_visit_token')
    op.drop_table('pmo_vaccination_visit_token')
