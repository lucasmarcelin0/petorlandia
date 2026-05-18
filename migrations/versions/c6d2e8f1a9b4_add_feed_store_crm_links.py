"""add feed store crm links

Revision ID: c6d2e8f1a9b4
Revises: b5e1c7a9d4f2
Create Date: 2026-05-18 01:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c6d2e8f1a9b4'
down_revision = 'b5e1c7a9d4f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('casa_de_racao_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_user_casa_de_racao_id'), ['casa_de_racao_id'], unique=False)
        batch_op.create_foreign_key(None, 'casa_de_racao', ['casa_de_racao_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('animal', schema=None) as batch_op:
        batch_op.add_column(sa.Column('casa_de_racao_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_animal_casa_de_racao_id'), ['casa_de_racao_id'], unique=False)
        batch_op.create_foreign_key(None, 'casa_de_racao', ['casa_de_racao_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('animal', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_animal_casa_de_racao_id'))
        batch_op.drop_column('casa_de_racao_id')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_user_casa_de_racao_id'))
        batch_op.drop_column('casa_de_racao_id')
