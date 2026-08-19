"""Add free-text clinical protocol proposals."""

from alembic import op
import sqlalchemy as sa


revision = 'e6c2a9f4b8d1'
down_revision = 'f2b8c4d6e1a9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'proposta_protocolo_clinico',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clinica_id', sa.Integer(), nullable=False),
        sa.Column('consulta_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('titulo', sa.String(length=160), nullable=False),
        sa.Column('categoria', sa.String(length=30), nullable=False, server_default='doenca'),
        sa.Column('especie', sa.String(length=40), nullable=True),
        sa.Column('conteudo_livre', sa.Text(), nullable=False),
        sa.Column('referencias', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='pending_review'),
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('protocolo_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['clinica_id'], ['clinica.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['consulta_id'], ['consulta.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['protocolo_id'], ['protocolo_clinico.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_proposta_protocolo_clinico_clinica_id',
        'proposta_protocolo_clinico',
        ['clinica_id'],
    )
    op.create_index(
        'ix_proposta_protocolo_clinico_consulta_id',
        'proposta_protocolo_clinico',
        ['consulta_id'],
    )
    op.create_index(
        'ix_proposta_protocolo_clinico_created_by',
        'proposta_protocolo_clinico',
        ['created_by'],
    )
    op.create_index(
        'ix_proposta_protocolo_clinico_categoria',
        'proposta_protocolo_clinico',
        ['categoria'],
    )
    op.create_index(
        'ix_proposta_protocolo_clinico_especie',
        'proposta_protocolo_clinico',
        ['especie'],
    )
    op.create_index(
        'ix_proposta_protocolo_clinico_status',
        'proposta_protocolo_clinico',
        ['status'],
    )
    op.create_index(
        'ix_proposta_protocolo_clinico_protocolo_id',
        'proposta_protocolo_clinico',
        ['protocolo_id'],
    )


def downgrade():
    op.drop_index(
        'ix_proposta_protocolo_clinico_protocolo_id',
        table_name='proposta_protocolo_clinico',
    )
    op.drop_index(
        'ix_proposta_protocolo_clinico_status',
        table_name='proposta_protocolo_clinico',
    )
    op.drop_index(
        'ix_proposta_protocolo_clinico_especie',
        table_name='proposta_protocolo_clinico',
    )
    op.drop_index(
        'ix_proposta_protocolo_clinico_categoria',
        table_name='proposta_protocolo_clinico',
    )
    op.drop_index(
        'ix_proposta_protocolo_clinico_created_by',
        table_name='proposta_protocolo_clinico',
    )
    op.drop_index(
        'ix_proposta_protocolo_clinico_consulta_id',
        table_name='proposta_protocolo_clinico',
    )
    op.drop_index(
        'ix_proposta_protocolo_clinico_clinica_id',
        table_name='proposta_protocolo_clinico',
    )
    op.drop_table('proposta_protocolo_clinico')
