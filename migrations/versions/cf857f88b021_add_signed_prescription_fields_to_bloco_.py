"""add signed prescription fields to bloco_prescricao

Revision ID: cf857f88b021
Revises: e2a4c6d8f0b1
Create Date: 2026-07-06 11:40:29.010053

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cf857f88b021'
down_revision = 'e2a4c6d8f0b1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('bloco_prescricao')]

    with op.batch_alter_table('bloco_prescricao', schema=None) as batch_op:
        if 'assinatura_arquivo_url' not in columns:
            batch_op.add_column(sa.Column('assinatura_arquivo_url', sa.String(length=500), nullable=True))
        if 'assinatura_enviada_em' not in columns:
            batch_op.add_column(sa.Column('assinatura_enviada_em', sa.DateTime(timezone=True), nullable=True))
        if 'assinatura_enviada_por_id' not in columns:
            batch_op.add_column(sa.Column('assinatura_enviada_por_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                'fk_bloco_prescricao_assinatura_enviada_por_id_user',
                'user',
                ['assinatura_enviada_por_id'],
                ['id'],
            )


def downgrade():
    with op.batch_alter_table('bloco_prescricao', schema=None) as batch_op:
        batch_op.drop_constraint('fk_bloco_prescricao_assinatura_enviada_por_id_user', type_='foreignkey')
        batch_op.drop_column('assinatura_enviada_por_id')
        batch_op.drop_column('assinatura_enviada_em')
        batch_op.drop_column('assinatura_arquivo_url')
