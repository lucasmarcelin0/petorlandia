"""add modo_entrega to casa_de_racao and delivery_request vendor fields

Revision ID: 6af8d65efabb
Revises: 4e0e2c0b768d
Create Date: 2026-05-14 13:32:00.689874

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6af8d65efabb'
down_revision = '4e0e2c0b768d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('casa_de_racao', schema=None) as batch_op:
        batch_op.add_column(sa.Column('modo_entrega', sa.String(length=20), nullable=False, server_default='plataforma'))

    with op.batch_alter_table('delivery_request', schema=None) as batch_op:
        batch_op.add_column(sa.Column('clinica_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('casa_de_racao_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('tipo_entrega', sa.String(length=20), nullable=False, server_default='plataforma'))
        batch_op.create_index(batch_op.f('ix_delivery_request_casa_de_racao_id'), ['casa_de_racao_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_delivery_request_clinica_id'), ['clinica_id'], unique=False)
        batch_op.create_foreign_key(None, 'casa_de_racao', ['casa_de_racao_id'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key(None, 'clinica', ['clinica_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('delivery_request', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_delivery_request_clinica_id'))
        batch_op.drop_index(batch_op.f('ix_delivery_request_casa_de_racao_id'))
        batch_op.drop_column('tipo_entrega')
        batch_op.drop_column('casa_de_racao_id')
        batch_op.drop_column('clinica_id')

    with op.batch_alter_table('casa_de_racao', schema=None) as batch_op:
        batch_op.drop_column('modo_entrega')
