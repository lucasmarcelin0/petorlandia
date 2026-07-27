"""Add habilitacao/supervisor to veterinario and make crmv nullable

Estagiários passam a ter ficha de profissional (agenda, horários, prontuário)
sem CRMV inventado. `habilitacao` diz quem pode assinar ato veterinário e
`supervisor_id` aponta o responsável técnico de cada estagiário.

Revision ID: d1e5f9a4c7b2
Revises: a3c9e7f1d2b8
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa


revision = 'd1e5f9a4c7b2'
down_revision = 'a3c9e7f1d2b8'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    colunas = {c['name'] for c in inspector.get_columns('veterinario')}

    # Tudo num único batch: o SQLite não suporta ALTER de constraint fora do
    # modo batch (copy-and-move), e a suíte roda contra SQLite.
    with op.batch_alter_table('veterinario') as batch:
        if 'habilitacao' not in colunas:
            batch.add_column(
                sa.Column(
                    'habilitacao',
                    sa.String(length=20),
                    nullable=False,
                    server_default='crmv',
                )
            )
        if 'supervisor_id' not in colunas:
            batch.add_column(sa.Column('supervisor_id', sa.Integer(), nullable=True))
            # Nomeada para poder ser removida no downgrade.
            batch.create_foreign_key(
                'fk_veterinario_supervisor_id',
                'veterinario',
                ['supervisor_id'],
                ['id'],
                ondelete='SET NULL',
            )
            batch.create_index('ix_veterinario_supervisor_id', ['supervisor_id'])
        # Estagiário não tem CRMV.
        batch.alter_column(
            'crmv',
            existing_type=sa.String(length=20),
            nullable=True,
        )


def downgrade():
    with op.batch_alter_table('veterinario') as batch:
        batch.drop_index('ix_veterinario_supervisor_id')
        batch.drop_constraint('fk_veterinario_supervisor_id', type_='foreignkey')
        batch.drop_column('supervisor_id')
        batch.drop_column('habilitacao')

    # Volta crmv a NOT NULL: quem estava sem número (estagiário) recebe um
    # marcador explícito, nunca um número plausível que possa ser confundido
    # com registro real.
    op.execute("UPDATE veterinario SET crmv = 'SEM-CRMV' WHERE crmv IS NULL")
    with op.batch_alter_table('veterinario') as batch:
        batch.alter_column(
            'crmv',
            existing_type=sa.String(length=20),
            nullable=False,
        )
