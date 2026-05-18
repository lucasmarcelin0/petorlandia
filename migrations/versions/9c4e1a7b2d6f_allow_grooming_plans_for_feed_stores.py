"""allow grooming plans for feed stores

Revision ID: 9c4e1a7b2d6f
Revises: 8b3d9f2a4c1e
Create Date: 2026-05-18 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '9c4e1a7b2d6f'
down_revision = '8b3d9f2a4c1e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('grooming_plan', schema=None) as batch_op:
        batch_op.alter_column('clinica_id', existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column('casa_de_racao_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_grooming_plan_casa_de_racao_id'), ['casa_de_racao_id'], unique=False)
        batch_op.create_foreign_key(None, 'casa_de_racao', ['casa_de_racao_id'], ['id'], ondelete='CASCADE')


def downgrade():
    with op.batch_alter_table('grooming_plan', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_grooming_plan_casa_de_racao_id'))
        batch_op.drop_column('casa_de_racao_id')
        batch_op.alter_column('clinica_id', existing_type=sa.Integer(), nullable=False)
