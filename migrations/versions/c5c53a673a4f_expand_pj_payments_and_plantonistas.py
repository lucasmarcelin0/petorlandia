"""expand pj payments and plantonista escalas

Revision ID: c5c53a673a4f
Revises: a99a4be65f35
Create Date: 2025-05-30 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from decimal import Decimal

# revision identifiers, used by Alembic.
revision = 'c5c53a673a4f'
down_revision = 'a99a4be65f35'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # --- pj_payments columns
    op.add_column('pj_payments', sa.Column('prestador_tipo', sa.String(length=20), nullable=False, server_default='pj'))
    op.add_column('pj_payments', sa.Column('valor_hora', sa.Numeric(10, 2), nullable=True))
    op.add_column('pj_payments', sa.Column('horas_previstas', sa.Numeric(6, 2), nullable=True))
    op.add_column('pj_payments', sa.Column('turno_inicio', sa.DateTime(), nullable=True))
    op.add_column('pj_payments', sa.Column('turno_fim', sa.DateTime(), nullable=True))
    op.add_column('pj_payments', sa.Column('plantonista_escala_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_pj_payments_plantonista',
        'pj_payments',
        'plantonista_escalas',
        ['plantonista_escala_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_unique_constraint('uq_pj_payment_plantonista', 'pj_payments', ['plantonista_escala_id'])
    op.alter_column('pj_payments', 'prestador_tipo', server_default=None)

    # --- plantonista_escalas columns
    op.add_column('plantonista_escalas', sa.Column('veterinario_id', sa.Integer(), nullable=True))
    op.add_column('plantonista_escalas', sa.Column('prestador_tipo', sa.String(length=20), nullable=False, server_default='pj'))
    op.add_column('plantonista_escalas', sa.Column('prestador_nome', sa.String(length=150), nullable=True))
    op.add_column('plantonista_escalas', sa.Column('prestador_cnpj', sa.String(length=20), nullable=True))
    op.add_column('plantonista_escalas', sa.Column('turno_inicio', sa.DateTime(), nullable=True))
    op.add_column('plantonista_escalas', sa.Column('turno_fim', sa.DateTime(), nullable=True))
    op.add_column('plantonista_escalas', sa.Column('valor_hora', sa.Numeric(10, 2), nullable=True))
    op.add_column('plantonista_escalas', sa.Column('horas_previstas', sa.Numeric(6, 2), nullable=True))
    op.create_index('ix_plantonista_escalas_veterinario_id', 'plantonista_escalas', ['veterinario_id'])
    op.create_index('ix_plantonista_escalas_turno_inicio', 'plantonista_escalas', ['turno_inicio'])
    op.create_foreign_key(
        'fk_plantonista_escalas_veterinario',
        'plantonista_escalas',
        'veterinario',
        ['veterinario_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.alter_column('plantonista_escalas', 'prestador_tipo', server_default=None)

    # --- migrate existing data
    bind.execute(
        text(
            """
            UPDATE plantonista_escalas
            SET prestador_nome = medico_nome,
                prestador_cnpj = medico_cnpj,
                veterinario_id = medico_id,
                turno_inicio = inicio,
                turno_fim = fim
            WHERE prestador_nome IS NULL
            """
        )
    )
    rows = bind.execute(
        text(
            "SELECT id, inicio, fim, valor_previsto FROM plantonista_escalas"
        )
    ).fetchall()
    for row in rows:
        horas = None
        valor_hora = None
        inicio = row['inicio']
        fim = row['fim']
        if inicio and fim:
            delta = fim - inicio
            horas = (Decimal(delta.total_seconds()) / Decimal('3600')).quantize(Decimal('0.01'))
        valor_previsto = row['valor_previsto']
        if valor_previsto is not None and horas and horas > 0:
            valor_hora = (Decimal(valor_previsto) / horas).quantize(Decimal('0.01'))
        bind.execute(
            text(
                """
                UPDATE plantonista_escalas
                SET horas_previstas = COALESCE(:horas, horas_previstas),
                    valor_hora = COALESCE(valor_hora, :valor_hora)
                WHERE id = :id
                """
            ),
            {
                'horas': horas,
                'valor_hora': valor_hora,
                'id': row['id'],
            },
        )
    bind.execute(text("UPDATE plantonista_escalas SET prestador_tipo = 'pj' WHERE prestador_tipo IS NULL"))
    bind.execute(text("UPDATE pj_payments SET prestador_tipo = 'pj' WHERE prestador_tipo IS NULL"))
    bind.execute(
        text(
            """
            UPDATE pj_payments AS pp
            SET plantonista_escala_id = pe.id
            FROM plantonista_escalas AS pe
            WHERE pe.pj_payment_id = pp.id AND pp.plantonista_escala_id IS NULL
            """
        )
    )
    bind.execute(
        text(
            """
            UPDATE pj_payments AS pp
            SET valor_hora = COALESCE(pp.valor_hora, pe.valor_hora),
                horas_previstas = COALESCE(pp.horas_previstas, pe.horas_previstas),
                turno_inicio = COALESCE(pp.turno_inicio, pe.turno_inicio),
                turno_fim = COALESCE(pp.turno_fim, pe.turno_fim)
            FROM plantonista_escalas AS pe
            WHERE pe.id = pp.plantonista_escala_id
            """
        )
    )

    op.alter_column('plantonista_escalas', 'prestador_nome', nullable=False, existing_type=sa.String(length=150))
    op.alter_column('plantonista_escalas', 'turno_inicio', nullable=False, existing_type=sa.DateTime())
    op.alter_column('plantonista_escalas', 'turno_fim', nullable=False, existing_type=sa.DateTime())

    # --- drop old references/columns
    op.drop_index('ix_plantonista_escalas_medico_id', table_name='plantonista_escalas')
    op.drop_index('ix_plantonista_escalas_inicio', table_name='plantonista_escalas')
    op.drop_constraint('plantonista_escalas_medico_id_fkey', 'plantonista_escalas', type_='foreignkey')
    op.drop_constraint('plantonista_escalas_pj_payment_id_fkey', 'plantonista_escalas', type_='foreignkey')
    op.drop_column('plantonista_escalas', 'pj_payment_id')
    op.drop_column('plantonista_escalas', 'medico_id')
    op.drop_column('plantonista_escalas', 'medico_nome')
    op.drop_column('plantonista_escalas', 'medico_cnpj')
    op.drop_column('plantonista_escalas', 'inicio')
    op.drop_column('plantonista_escalas', 'fim')


def downgrade():
    bind = op.get_bind()

    # restore legacy columns on plantonista_escalas
    op.add_column('plantonista_escalas', sa.Column('fim', sa.DateTime(), nullable=True))
    op.add_column('plantonista_escalas', sa.Column('inicio', sa.DateTime(), nullable=True))
    op.add_column('plantonista_escalas', sa.Column('medico_cnpj', sa.String(length=20), nullable=True))
    op.add_column('plantonista_escalas', sa.Column('medico_nome', sa.String(length=150), nullable=True))
    op.add_column('plantonista_escalas', sa.Column('medico_id', sa.Integer(), nullable=True))
    op.add_column('plantonista_escalas', sa.Column('pj_payment_id', sa.Integer(), nullable=True))

    # copy data back to legacy columns
    bind.execute(
        text(
            """
            UPDATE plantonista_escalas
            SET medico_id = veterinario_id,
                medico_nome = prestador_nome,
                medico_cnpj = prestador_cnpj,
                inicio = turno_inicio,
                fim = turno_fim
            """
        )
    )
    bind.execute(
        text(
            """
            UPDATE plantonista_escalas AS pe
            SET pj_payment_id = pp.id
            FROM pj_payments AS pp
            WHERE pp.plantonista_escala_id = pe.id
            """
        )
    )

    # recreate indexes/constraints for legacy columns
    op.create_index('ix_plantonista_escalas_medico_id', 'plantonista_escalas', ['medico_id'])
    op.create_index('ix_plantonista_escalas_inicio', 'plantonista_escalas', ['inicio'])
    op.create_foreign_key('plantonista_escalas_medico_id_fkey', 'plantonista_escalas', 'veterinario', ['medico_id'], ['id'])
    op.create_foreign_key('plantonista_escalas_pj_payment_id_fkey', 'plantonista_escalas', 'pj_payments', ['pj_payment_id'], ['id'])

    # drop new indexes/constraints
    op.drop_constraint('fk_plantonista_escalas_veterinario', 'plantonista_escalas', type_='foreignkey')
    op.drop_index('ix_plantonista_escalas_veterinario_id', table_name='plantonista_escalas')
    op.drop_index('ix_plantonista_escalas_turno_inicio', table_name='plantonista_escalas')

    # drop columns added in upgrade
    op.drop_column('plantonista_escalas', 'horas_previstas')
    op.drop_column('plantonista_escalas', 'valor_hora')
    op.drop_column('plantonista_escalas', 'turno_fim')
    op.drop_column('plantonista_escalas', 'turno_inicio')
    op.drop_column('plantonista_escalas', 'prestador_cnpj')
    op.drop_column('plantonista_escalas', 'prestador_nome')
    op.drop_column('plantonista_escalas', 'prestador_tipo')
    op.drop_column('plantonista_escalas', 'veterinario_id')

    # restore NOT NULL constraints on legacy columns
    op.alter_column('plantonista_escalas', 'medico_nome', nullable=False, existing_type=sa.String(length=150))
    op.alter_column('plantonista_escalas', 'inicio', nullable=False, existing_type=sa.DateTime())
    op.alter_column('plantonista_escalas', 'fim', nullable=False, existing_type=sa.DateTime())

    # revert pj_payments additions
    op.drop_constraint('uq_pj_payment_plantonista', 'pj_payments', type_='unique')
    op.drop_constraint('fk_pj_payments_plantonista', 'pj_payments', type_='foreignkey')
    op.drop_column('pj_payments', 'plantonista_escala_id')
    op.drop_column('pj_payments', 'turno_fim')
    op.drop_column('pj_payments', 'turno_inicio')
    op.drop_column('pj_payments', 'horas_previstas')
    op.drop_column('pj_payments', 'valor_hora')
    op.drop_column('pj_payments', 'prestador_tipo')
