"""lembretes de vacinas atrasadas: opção da clínica, envios e descadastro

Revision ID: e7a3c9d5b1f4
Revises: c4f8a1d6e9b3
Create Date: 2026-11-03 10:00:00.000000

Uma coluna nova em ``clinica`` (desligada por padrão) e duas tabelas novas.
Nada muda nos dados existentes.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e7a3c9d5b1f4'
down_revision = 'c4f8a1d6e9b3'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {col['name'] for col in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if 'lembrete_vacina_automatico' not in _columns('clinica'):
        op.add_column(
            'clinica',
            sa.Column('lembrete_vacina_automatico', sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    tables = _tables()
    if 'lembrete_vacina_envio' not in tables:
        op.create_table(
            'lembrete_vacina_envio',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('clinica_id', sa.Integer(), nullable=False),
            sa.Column('animal_id', sa.Integer(), nullable=False),
            sa.Column('vacina_id', sa.Integer(), nullable=False),
            sa.Column('tutor_id', sa.Integer(), nullable=True),
            sa.Column('vencimento', sa.Date(), nullable=False),
            sa.Column('canal', sa.String(length=20), nullable=False),
            sa.Column('origem', sa.String(length=20), nullable=False),
            sa.Column('marco', sa.Integer(), nullable=True),
            sa.Column('enviado_por_id', sa.Integer(), nullable=True),
            sa.Column('enviado_em', sa.DateTime(timezone=True), nullable=False),
            sa.Column('chave', sa.String(length=120), nullable=True),
            sa.ForeignKeyConstraint(['clinica_id'], ['clinica.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['animal_id'], ['animal.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['vacina_id'], ['vacina.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['tutor_id'], ['user.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['enviado_por_id'], ['user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('chave', name='uq_lembrete_vacina_envio_chave'),
        )
        op.create_index('ix_lembrete_vacina_envio_clinica_id', 'lembrete_vacina_envio', ['clinica_id'])
        op.create_index('ix_lembrete_vacina_envio_animal_id', 'lembrete_vacina_envio', ['animal_id'])
        op.create_index('ix_lembrete_vacina_envio_vacina_id', 'lembrete_vacina_envio', ['vacina_id'])
        op.create_index('ix_lembrete_vacina_envio_tutor_id', 'lembrete_vacina_envio', ['tutor_id'])

    if 'lembrete_vacina_bloqueio' not in tables:
        op.create_table(
            'lembrete_vacina_bloqueio',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', name='uq_lembrete_vacina_bloqueio_user'),
        )


def downgrade():
    tables = _tables()
    if 'lembrete_vacina_bloqueio' in tables:
        op.drop_table('lembrete_vacina_bloqueio')
    if 'lembrete_vacina_envio' in tables:
        op.drop_table('lembrete_vacina_envio')
    if 'lembrete_vacina_automatico' in _columns('clinica'):
        op.drop_column('clinica', 'lembrete_vacina_automatico')
