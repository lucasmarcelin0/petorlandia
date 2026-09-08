"""add clinica_id to exame_modelo

Permite isolar modelos de exame por clínica (ex.: serviço exclusivo da PetOrlândia),
mantendo exames com clinica_id nulo visíveis globalmente como padrão da plataforma.

Revision ID: b1e5a2c9f100
Revises: a7d1c3e9f240
Create Date: 2026-09-08

"""
from alembic import op
import sqlalchemy as sa


revision = 'b1e5a2c9f100'
down_revision = 'a7d1c3e9f240'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('exame_modelo')]

    if 'clinica_id' not in columns:
        op.add_column('exame_modelo', sa.Column('clinica_id', sa.Integer(), nullable=True))
        try:
            op.create_foreign_key(
                'fk_exame_modelo_clinica_id',
                'exame_modelo',
                'clinica',
                ['clinica_id'],
                ['id'],
                ondelete='SET NULL',
            )
        except Exception:
            # Em SQLite ou bases onde ALTER TABLE ADD CONSTRAINT não é suportado
            pass
        try:
            op.create_index(
                op.f('ix_exame_modelo_clinica_id'),
                'exame_modelo',
                ['clinica_id'],
                unique=False,
            )
        except Exception:
            pass


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('exame_modelo')]

    if 'clinica_id' in columns:
        try:
            op.drop_index(op.f('ix_exame_modelo_clinica_id'), table_name='exame_modelo')
        except Exception:
            pass
        try:
            op.drop_constraint('fk_exame_modelo_clinica_id', 'exame_modelo', type_='foreignkey')
        except Exception:
            pass
        op.drop_column('exame_modelo', 'clinica_id')
