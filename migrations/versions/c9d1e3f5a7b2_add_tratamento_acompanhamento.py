"""Add treatment follow-up tables (acompanhamento de tratamento)

Revision ID: c9d1e3f5a7b2
Revises: a3f8d2c1e5b7
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9d1e3f5a7b2'
down_revision = 'a3f8d2c1e5b7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tratamento_acompanhamento',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bloco_id', sa.Integer(), nullable=False),
        sa.Column('animal_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='ativo'),
        sa.Column('data_inicio', sa.DateTime(timezone=True), nullable=True),
        sa.Column('criado_por_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['bloco_id'], ['bloco_prescricao.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['animal_id'], ['animal.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['criado_por_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('bloco_id'),
    )
    op.create_index(
        'ix_tratamento_acompanhamento_animal_id',
        'tratamento_acompanhamento',
        ['animal_id'],
    )

    op.create_table(
        'item_tratamento',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('acompanhamento_id', sa.Integer(), nullable=False),
        sa.Column('prescricao_id', sa.Integer(), nullable=False),
        sa.Column('modo', sa.String(length=10), nullable=False, server_default='livre'),
        sa.Column('intervalo_horas', sa.Integer(), nullable=True),
        sa.Column('duracao_dias', sa.Integer(), nullable=True),
        sa.Column('comprado_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('comprado_por_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['acompanhamento_id'], ['tratamento_acompanhamento.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['prescricao_id'], ['prescricao.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['comprado_por_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_item_tratamento_acompanhamento_id',
        'item_tratamento',
        ['acompanhamento_id'],
    )

    op.create_table(
        'administracao_registro',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('prevista_para', sa.DateTime(timezone=True), nullable=True),
        sa.Column('realizada_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('realizada_por_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='pendente'),
        sa.Column('observacao', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['item_tratamento.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['realizada_por_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_administracao_registro_item_id',
        'administracao_registro',
        ['item_id'],
    )

    op.create_table(
        'foto_tratamento',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('acompanhamento_id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(length=400), nullable=False),
        sa.Column('observacao', sa.Text(), nullable=True),
        sa.Column('enviada_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('enviada_por_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['acompanhamento_id'], ['tratamento_acompanhamento.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['enviada_por_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_foto_tratamento_acompanhamento_id',
        'foto_tratamento',
        ['acompanhamento_id'],
    )


def downgrade():
    op.drop_index('ix_foto_tratamento_acompanhamento_id', table_name='foto_tratamento')
    op.drop_table('foto_tratamento')
    op.drop_index('ix_administracao_registro_item_id', table_name='administracao_registro')
    op.drop_table('administracao_registro')
    op.drop_index('ix_item_tratamento_acompanhamento_id', table_name='item_tratamento')
    op.drop_table('item_tratamento')
    op.drop_index('ix_tratamento_acompanhamento_animal_id', table_name='tratamento_acompanhamento')
    op.drop_table('tratamento_acompanhamento')
