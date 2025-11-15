"""add plantonista support

Revision ID: 2d57aef3d049
Revises: fa2b77d13374
Create Date: 2024-05-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        'plantonista_escala',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=False),
        sa.Column('veterinario_id', sa.Integer(), nullable=True),
        sa.Column('prestador_nome', sa.String(length=150), nullable=True),
        sa.Column('turno_inicio', sa.DateTime(), nullable=False),
        sa.Column('turno_fim', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=40), nullable=False, server_default='executado'),
        sa.Column('valor_previsto', sa.Numeric(14, 2), nullable=False, server_default='0.00'),
        sa.Column('observacoes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinica.id']),
        sa.ForeignKeyConstraint(['veterinario_id'], ['veterinario.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_plantonista_escala_clinic_id', 'plantonista_escala', ['clinic_id'])
    op.create_index('ix_plantonista_escala_veterinario_id', 'plantonista_escala', ['veterinario_id'])
    op.create_index('ix_plantonista_escala_turno_inicio', 'plantonista_escala', ['turno_inicio'])
    op.create_index('ix_plantonista_escala_turno_fim', 'plantonista_escala', ['turno_fim'])
    op.create_index('ix_plantonista_escala_status', 'plantonista_escala', ['status'])

    op.add_column('pj_payments', sa.Column('tipo_prestador', sa.String(length=40), nullable=False, server_default='prestador'))
    op.add_column('pj_payments', sa.Column('plantonista_id', sa.Integer(), nullable=True))
    op.add_column('pj_payments', sa.Column('horas_previstas', sa.Numeric(6, 2), nullable=True))
    op.add_column('pj_payments', sa.Column('valor_hora', sa.Numeric(10, 2), nullable=True))
    op.add_column('pj_payments', sa.Column('retencao_obrigatoria', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.create_index('ix_pj_payments_tipo_prestador', 'pj_payments', ['tipo_prestador'])
    op.create_index('ix_pj_payments_plantonista_id', 'pj_payments', ['plantonista_id'])
    op.create_foreign_key('fk_pj_payments_plantonista_id', 'pj_payments', 'plantonista_escala', ['plantonista_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_pj_payments_plantonista_id', 'pj_payments', type_='foreignkey')
    op.drop_index('ix_pj_payments_plantonista_id', table_name='pj_payments')
    op.drop_index('ix_pj_payments_tipo_prestador', table_name='pj_payments')
    op.drop_column('pj_payments', 'retencao_obrigatoria')
    op.drop_column('pj_payments', 'valor_hora')
    op.drop_column('pj_payments', 'horas_previstas')
    op.drop_column('pj_payments', 'plantonista_id')
    op.drop_column('pj_payments', 'tipo_prestador')

    op.drop_index('ix_plantonista_escala_status', table_name='plantonista_escala')
    op.drop_index('ix_plantonista_escala_turno_fim', table_name='plantonista_escala')
    op.drop_index('ix_plantonista_escala_turno_inicio', table_name='plantonista_escala')
    op.drop_index('ix_plantonista_escala_veterinario_id', table_name='plantonista_escala')
    op.drop_index('ix_plantonista_escala_clinic_id', table_name='plantonista_escala')
    op.drop_table('plantonista_escala')
