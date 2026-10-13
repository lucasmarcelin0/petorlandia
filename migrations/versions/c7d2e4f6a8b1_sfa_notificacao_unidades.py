"""sfa: unidades de saude notificadoras, responsaveis e autoria da ficha SINAN

Revision ID: c7d2e4f6a8b1
Revises: b3f7a2d9c5e1
Create Date: 2026-10-13 15:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c7d2e4f6a8b1'
down_revision = 'b3f7a2d9c5e1'
branch_labels = None
depends_on = None


# As seis unidades que a ficha digital ja sugeria no campo 6. O administrador
# pode renomear, desativar ou cadastrar outras pela tela.
UNIDADES_INICIAIS = (
    ('Hospital Beneficente Santo Antônio', '2745798', '(16) 3820-4200'),
    ('CAPS I Sebastião Boschin', '6746012', '(16) 3820-8244'),
    ('UBS I Américo Alves', '2746115', '(16) 3826-7333'),
    ('UBS II José Marchi', '2746123', None),
    ('UBS III Waldemar Graner', '2746131', None),
    ('CS II Dr. Miguel Vitaliano', '2745690', None),
)


def upgrade():
    unidade = op.create_table(
        'sfa_unidade_saude',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('nome', sa.String(length=180), nullable=False),
        sa.Column('cnes', sa.String(length=12), nullable=True),
        sa.Column('telefone', sa.String(length=25), nullable=True),
        sa.Column('apelidos', sa.Text(), nullable=True),
        sa.Column('ativa', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('criado_por', sa.String(length=160), nullable=False),
        sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_sfa_unidade_saude_cnes', 'sfa_unidade_saude', ['cnes'])

    op.create_table(
        'sfa_unidade_responsavel',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('unidade_id', sa.Integer(), sa.ForeignKey('sfa_unidade_saude.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('concedido_por', sa.String(length=160), nullable=False),
        sa.Column('concedido_em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('revogado_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revogado_por', sa.String(length=160), nullable=True),
    )
    op.create_index('ix_sfa_unidade_responsavel_unidade_id', 'sfa_unidade_responsavel', ['unidade_id'])
    op.create_index('ix_sfa_unidade_responsavel_user_id', 'sfa_unidade_responsavel', ['user_id'])

    op.add_column('sfa_sinan_log', sa.Column('agravo', sa.String(length=40), nullable=True))
    op.add_column('sfa_sinan_log', sa.Column('unidade_notificante', sa.String(length=180), nullable=True))
    op.add_column('sfa_sinan_log', sa.Column('unidade_id', sa.Integer(), nullable=True))
    op.add_column('sfa_sinan_log', sa.Column('preenchido_por_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_sfa_sinan_log_unidade', 'sfa_sinan_log', 'sfa_unidade_saude', ['unidade_id'], ['id'])
    op.create_foreign_key('fk_sfa_sinan_log_preenchido_por', 'sfa_sinan_log', 'user', ['preenchido_por_id'], ['id'])
    op.create_index('ix_sfa_sinan_log_unidade_id', 'sfa_sinan_log', ['unidade_id'])
    op.create_index('ix_sfa_sinan_log_preenchido_por_id', 'sfa_sinan_log', ['preenchido_por_id'])

    op.bulk_insert(unidade, [
        {'nome': nome, 'cnes': cnes, 'telefone': telefone, 'criado_por': 'Cadastro inicial'}
        for nome, cnes, telefone in UNIDADES_INICIAIS
    ])


def downgrade():
    op.drop_index('ix_sfa_sinan_log_preenchido_por_id', table_name='sfa_sinan_log')
    op.drop_index('ix_sfa_sinan_log_unidade_id', table_name='sfa_sinan_log')
    op.drop_constraint('fk_sfa_sinan_log_preenchido_por', 'sfa_sinan_log', type_='foreignkey')
    op.drop_constraint('fk_sfa_sinan_log_unidade', 'sfa_sinan_log', type_='foreignkey')
    for coluna in ('preenchido_por_id', 'unidade_id', 'unidade_notificante', 'agravo'):
        op.drop_column('sfa_sinan_log', coluna)
    op.drop_index('ix_sfa_unidade_responsavel_user_id', table_name='sfa_unidade_responsavel')
    op.drop_index('ix_sfa_unidade_responsavel_unidade_id', table_name='sfa_unidade_responsavel')
    op.drop_table('sfa_unidade_responsavel')
    op.drop_index('ix_sfa_unidade_saude_cnes', table_name='sfa_unidade_saude')
    op.drop_table('sfa_unidade_saude')
