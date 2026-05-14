"""add casa_de_racao tables and product fk

Revision ID: 4e0e2c0b768d
Revises: c2d4e1f8a9b3
Create Date: 2026-05-14 12:39:41.181940

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4e0e2c0b768d'
down_revision = 'c2d4e1f8a9b3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('casa_de_racao',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=120), nullable=False),
    sa.Column('razao_social', sa.String(length=200), nullable=True),
    sa.Column('cnpj', sa.String(length=18), nullable=True),
    sa.Column('descricao', sa.Text(), nullable=True),
    sa.Column('telefone', sa.String(length=20), nullable=True),
    sa.Column('email', sa.String(length=120), nullable=True),
    sa.Column('endereco', sa.String(length=200), nullable=True),
    sa.Column('logotipo', sa.String(length=200), nullable=True),
    sa.Column('photo_rotation', sa.Integer(), nullable=True),
    sa.Column('photo_zoom', sa.Float(), nullable=True),
    sa.Column('photo_offset_x', sa.Float(), nullable=True),
    sa.Column('photo_offset_y', sa.Float(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cnpj')
    )
    op.create_table('casa_de_racao_horario',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
    sa.Column('dia_semana', sa.String(length=20), nullable=False),
    sa.Column('hora_abertura', sa.Time(), nullable=False),
    sa.Column('hora_fechamento', sa.Time(), nullable=False),
    sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.add_column(sa.Column('casa_de_racao_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_product_casa_de_racao_id'), ['casa_de_racao_id'], unique=False)
        batch_op.create_foreign_key(None, 'casa_de_racao', ['casa_de_racao_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_product_casa_de_racao_id'))
        batch_op.drop_column('casa_de_racao_id')

    op.drop_table('casa_de_racao_horario')
    op.drop_table('casa_de_racao')
