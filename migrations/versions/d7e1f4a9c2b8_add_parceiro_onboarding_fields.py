"""add parceiro onboarding fields (registered_by_id, casa_de_racao.tipo)

Adiciona o rastreamento de quem cadastrou cada estabelecimento (conta de
Parceiro de Cadastro) e o subtipo da loja de varejo.

Revision ID: d7e1f4a9c2b8
Revises: 7dd91845a619
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa


revision = 'd7e1f4a9c2b8'
down_revision = '7dd91845a619'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clinica') as batch:
        batch.add_column(sa.Column('registered_by_id', sa.Integer(), nullable=True))
        batch.create_index('ix_clinica_registered_by_id', ['registered_by_id'])
        batch.create_foreign_key(
            'fk_clinica_registered_by_id_user',
            'user', ['registered_by_id'], ['id'], ondelete='SET NULL',
        )

    with op.batch_alter_table('casa_de_racao') as batch:
        batch.add_column(
            sa.Column(
                'tipo', sa.String(length=20),
                nullable=False, server_default='casa_de_racao',
            )
        )
        batch.add_column(sa.Column('registered_by_id', sa.Integer(), nullable=True))
        batch.create_index('ix_casa_de_racao_registered_by_id', ['registered_by_id'])
        batch.create_foreign_key(
            'fk_casa_de_racao_registered_by_id_user',
            'user', ['registered_by_id'], ['id'], ondelete='SET NULL',
        )

    with op.batch_alter_table('petsitter_profile') as batch:
        batch.add_column(sa.Column('registered_by_id', sa.Integer(), nullable=True))
        batch.create_index('ix_petsitter_profile_registered_by_id', ['registered_by_id'])
        batch.create_foreign_key(
            'fk_petsitter_profile_registered_by_id_user',
            'user', ['registered_by_id'], ['id'], ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('petsitter_profile') as batch:
        batch.drop_constraint('fk_petsitter_profile_registered_by_id_user', type_='foreignkey')
        batch.drop_index('ix_petsitter_profile_registered_by_id')
        batch.drop_column('registered_by_id')

    with op.batch_alter_table('casa_de_racao') as batch:
        batch.drop_constraint('fk_casa_de_racao_registered_by_id_user', type_='foreignkey')
        batch.drop_index('ix_casa_de_racao_registered_by_id')
        batch.drop_column('registered_by_id')
        batch.drop_column('tipo')

    with op.batch_alter_table('clinica') as batch:
        batch.drop_constraint('fk_clinica_registered_by_id_user', type_='foreignkey')
        batch.drop_index('ix_clinica_registered_by_id')
        batch.drop_column('registered_by_id')
