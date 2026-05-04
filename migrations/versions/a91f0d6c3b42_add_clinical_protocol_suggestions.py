"""add clinical protocol suggestions

Revision ID: a91f0d6c3b42
Revises: d1a3f7c2b9e8
Create Date: 2026-05-04 20:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = 'a91f0d6c3b42'
down_revision = 'd1a3f7c2b9e8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('consulta') as batch:
        batch.add_column(sa.Column('suspeita_clinica', sa.String(length=160), nullable=True))
        batch.create_index(batch.f('ix_consulta_suspeita_clinica'), ['suspeita_clinica'], unique=False)

    op.create_table(
        'protocolo_clinico',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('suspeita_principal', sa.String(length=160), nullable=False),
        sa.Column('especie', sa.String(length=40), nullable=True),
        sa.Column('sinais_gatilho', sa.Text(), nullable=True),
        sa.Column('conduta_sugerida', sa.Text(), nullable=True),
        sa.Column('orientacoes_tutor', sa.Text(), nullable=True),
        sa.Column('alertas', sa.Text(), nullable=True),
        sa.Column('prioridade', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('versao', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('ativo', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('clinica_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['clinica_id'], ['clinica.id']),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_protocolo_clinico_suspeita_principal', 'protocolo_clinico', ['suspeita_principal'], unique=False)
    op.create_index('ix_protocolo_clinico_especie', 'protocolo_clinico', ['especie'], unique=False)

    op.create_table(
        'protocolo_clinico_exame',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('protocolo_id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('justificativa', sa.Text(), nullable=True),
        sa.Column('prioridade', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['protocolo_id'], ['protocolo_clinico.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_protocolo_clinico_exame_protocolo_id', 'protocolo_clinico_exame', ['protocolo_id'], unique=False)

    op.create_table(
        'protocolo_clinico_medicamento',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('protocolo_id', sa.Integer(), nullable=False),
        sa.Column('medicamento_id', sa.Integer(), nullable=True),
        sa.Column('nome_medicamento', sa.String(length=120), nullable=True),
        sa.Column('justificativa', sa.Text(), nullable=True),
        sa.Column('dosagem_texto', sa.Text(), nullable=True),
        sa.Column('frequencia_texto', sa.Text(), nullable=True),
        sa.Column('duracao_texto', sa.Text(), nullable=True),
        sa.Column('observacoes', sa.Text(), nullable=True),
        sa.Column('indicacao', sa.String(length=120), nullable=True),
        sa.Column('prioridade', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['medicamento_id'], ['medicamento.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['protocolo_id'], ['protocolo_clinico.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_protocolo_clinico_medicamento_protocolo_id',
        'protocolo_clinico_medicamento',
        ['protocolo_id'],
        unique=False,
    )

    op.create_table(
        'protocolo_clinico_retorno',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('protocolo_id', sa.Integer(), nullable=False),
        sa.Column('prazo_min_dias', sa.Integer(), nullable=True),
        sa.Column('prazo_max_dias', sa.Integer(), nullable=True),
        sa.Column('tipo_retorno', sa.String(length=40), nullable=False, server_default='retorno'),
        sa.Column('objetivo', sa.Text(), nullable=True),
        sa.Column('gatilhos_antecipacao', sa.Text(), nullable=True),
        sa.Column('prioridade', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['protocolo_id'], ['protocolo_clinico.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_protocolo_clinico_retorno_protocolo_id', 'protocolo_clinico_retorno', ['protocolo_id'], unique=False)

    op.create_table(
        'auditoria_sugestao_clinica',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('consulta_id', sa.Integer(), nullable=False),
        sa.Column('protocolo_id', sa.Integer(), nullable=True),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('tipo_item', sa.String(length=30), nullable=False),
        sa.Column('acao', sa.String(length=30), nullable=False),
        sa.Column('titulo_item', sa.String(length=200), nullable=True),
        sa.Column('justificativa', sa.Text(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['actor_user_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['consulta_id'], ['consulta.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['protocolo_id'], ['protocolo_clinico.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_auditoria_sugestao_clinica_consulta_id', 'auditoria_sugestao_clinica', ['consulta_id'], unique=False)
    op.create_index('ix_auditoria_sugestao_clinica_protocolo_id', 'auditoria_sugestao_clinica', ['protocolo_id'], unique=False)
    op.create_index('ix_auditoria_sugestao_clinica_actor_user_id', 'auditoria_sugestao_clinica', ['actor_user_id'], unique=False)
    op.create_index('ix_auditoria_sugestao_clinica_tipo_item', 'auditoria_sugestao_clinica', ['tipo_item'], unique=False)
    op.create_index('ix_auditoria_sugestao_clinica_acao', 'auditoria_sugestao_clinica', ['acao'], unique=False)


def downgrade():
    op.drop_index('ix_auditoria_sugestao_clinica_acao', table_name='auditoria_sugestao_clinica')
    op.drop_index('ix_auditoria_sugestao_clinica_tipo_item', table_name='auditoria_sugestao_clinica')
    op.drop_index('ix_auditoria_sugestao_clinica_actor_user_id', table_name='auditoria_sugestao_clinica')
    op.drop_index('ix_auditoria_sugestao_clinica_protocolo_id', table_name='auditoria_sugestao_clinica')
    op.drop_index('ix_auditoria_sugestao_clinica_consulta_id', table_name='auditoria_sugestao_clinica')
    op.drop_table('auditoria_sugestao_clinica')

    op.drop_index('ix_protocolo_clinico_retorno_protocolo_id', table_name='protocolo_clinico_retorno')
    op.drop_table('protocolo_clinico_retorno')

    op.drop_index('ix_protocolo_clinico_medicamento_protocolo_id', table_name='protocolo_clinico_medicamento')
    op.drop_table('protocolo_clinico_medicamento')

    op.drop_index('ix_protocolo_clinico_exame_protocolo_id', table_name='protocolo_clinico_exame')
    op.drop_table('protocolo_clinico_exame')

    op.drop_index('ix_protocolo_clinico_especie', table_name='protocolo_clinico')
    op.drop_index('ix_protocolo_clinico_suspeita_principal', table_name='protocolo_clinico')
    op.drop_table('protocolo_clinico')

    with op.batch_alter_table('consulta') as batch:
        batch.drop_index(batch.f('ix_consulta_suspeita_clinica'))
        batch.drop_column('suspeita_clinica')
