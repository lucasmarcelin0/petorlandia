"""link pmo animals to records

Revision ID: a8d2e4f9c1b7
Revises: f4a8c2e7b9d1
Create Date: 2026-05-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'a8d2e4f9c1b7'
down_revision = 'f4a8c2e7b9d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pmo_vaccination_animal', schema=None) as batch_op:
        batch_op.add_column(sa.Column('animal_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('vaccine_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_pmo_vaccination_animal_animal_id'), ['animal_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pmo_vaccination_animal_vaccine_id'), ['vaccine_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_pmo_vaccination_animal_animal_id_animal',
            'animal',
            ['animal_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_foreign_key(
            'fk_pmo_vaccination_animal_vaccine_id_vacina',
            'vacina',
            ['vaccine_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('pmo_vaccination_animal', schema=None) as batch_op:
        batch_op.drop_constraint('fk_pmo_vaccination_animal_vaccine_id_vacina', type_='foreignkey')
        batch_op.drop_constraint('fk_pmo_vaccination_animal_animal_id_animal', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_pmo_vaccination_animal_vaccine_id'))
        batch_op.drop_index(batch_op.f('ix_pmo_vaccination_animal_animal_id'))
        batch_op.drop_column('vaccine_id')
        batch_op.drop_column('animal_id')
