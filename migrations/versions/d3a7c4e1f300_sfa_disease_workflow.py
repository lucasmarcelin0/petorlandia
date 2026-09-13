"""SFA: T7 independente do T10 histórico e rastreabilidade do trabalho.

Revision ID: d3a7c4e1f300
Revises: c2f6b3d0e200
"""
from alembic import op
import sqlalchemy as sa

revision = 'd3a7c4e1f300'
down_revision = 'c2f6b3d0e200'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sfa_paciente', sa.Column('status_t7', sa.String(30)))
    op.add_column('sfa_paciente', sa.Column('data_t7', sa.String(15)))
    op.create_table('sfa_resposta_t7',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('id_estudo', sa.String(30), sa.ForeignKey('sfa_paciente.id_estudo')),
        sa.Column('timestamp', sa.DateTime(timezone=True)),
        sa.Column('dias_incap_novos', sa.Integer()),
        sa.Column('custo_remedios', sa.Numeric(10, 2)),
        sa.Column('custo_consultas', sa.Numeric(10, 2)),
        sa.Column('custo_transporte', sa.Numeric(10, 2)),
        sa.Column('custo_outros', sa.Numeric(10, 2)),
        sa.Column('dados_json', sa.Text()),
        sa.UniqueConstraint('id_estudo', name='uq_sfa_t7_episodio'))
    op.create_index('ix_sfa_resposta_t7_id_estudo', 'sfa_resposta_t7', ['id_estudo'])
    op.create_table('sfa_contexto_episodio',
        sa.Column('id_estudo', sa.String(30), sa.ForeignKey('sfa_paciente.id_estudo'), primary_key=True),
        sa.Column('inicio_sintomas', sa.Date()), sa.Column('fonte_inicio', sa.String(200)),
        sa.Column('responsavel', sa.String(160)), sa.Column('setor', sa.String(15)),
        sa.Column('malha', sa.String(30)), sa.Column('tipo_local', sa.String(30)),
        sa.Column('fonte_local', sa.String(200)), sa.Column('local_validado', sa.Boolean(), nullable=False),
        sa.Column('classificacao', sa.String(40)), sa.Column('fonte_classificacao', sa.String(200)),
        sa.Column('atualizado_em', sa.DateTime(timezone=True)))
    op.create_index('ix_sfa_contexto_episodio_setor', 'sfa_contexto_episodio', ['setor'])
    op.create_table('sfa_contato',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('id_estudo', sa.String(30), sa.ForeignKey('sfa_paciente.id_estudo'), nullable=False),
        sa.Column('ocorrido_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('etapa', sa.String(10), nullable=False), sa.Column('canal', sa.String(30), nullable=False),
        sa.Column('resultado', sa.String(30), nullable=False), sa.Column('responsavel', sa.String(160), nullable=False),
        sa.Column('motivo', sa.Text()), sa.Column('proximo_contato', sa.Date()))
    op.create_index('ix_sfa_contato_id_estudo', 'sfa_contato', ['id_estudo'])
    op.create_table('sfa_evento_coletivo',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('titulo', sa.String(200), nullable=False),
        sa.Column('local', sa.String(300), nullable=False), sa.Column('inicio', sa.Date(), nullable=False),
        sa.Column('fim', sa.Date()), sa.Column('exposicao', sa.Text(), nullable=False),
        sa.Column('avaliacao', sa.String(30), nullable=False), sa.Column('avaliador', sa.String(160)),
        sa.Column('justificativa', sa.Text()), sa.Column('avaliado_em', sa.DateTime(timezone=True)),
        sa.Column('criado_em', sa.DateTime(timezone=True)))
    op.create_table('sfa_evento_vinculo',
        sa.Column('evento_id', sa.Integer(), sa.ForeignKey('sfa_evento_coletivo.id'), primary_key=True),
        sa.Column('id_estudo', sa.String(30), sa.ForeignKey('sfa_paciente.id_estudo'), primary_key=True),
        sa.Column('fonte', sa.String(200), nullable=False), sa.Column('vinculado_em', sa.DateTime(timezone=True)))
    op.create_table('sfa_acao',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('id_estudo', sa.String(30), sa.ForeignKey('sfa_paciente.id_estudo')),
        sa.Column('evento_id', sa.Integer(), sa.ForeignKey('sfa_evento_coletivo.id')),
        sa.Column('setor', sa.String(15)), sa.Column('motivo', sa.Text(), nullable=False),
        sa.Column('tipo', sa.String(40), nullable=False), sa.Column('responsavel', sa.String(160), nullable=False),
        sa.Column('prazo', sa.Date(), nullable=False), sa.Column('status', sa.String(30), nullable=False),
        sa.Column('criado_em', sa.DateTime(timezone=True)), sa.Column('executado_em', sa.DateTime(timezone=True)),
        sa.Column('verificado_em', sa.DateTime(timezone=True)), sa.Column('resultado', sa.Text()),
        sa.Column('evidencia_verificacao', sa.Text()), sa.Column('verificador', sa.String(160)),
        sa.Column('horas', sa.Numeric(8, 2)), sa.Column('custo', sa.Numeric(10, 2)))
    for field in ('id_estudo', 'evento_id', 'status'):
        op.create_index(f'ix_sfa_acao_{field}', 'sfa_acao', [field])
    # Respostas e datas T10 permanecem intactas, sem serem copiadas para T7.
    op.execute("UPDATE sfa_paciente SET status_t7 = 'LEGADO_T10' WHERE EXISTS (SELECT 1 FROM sfa_resposta_t10 r WHERE r.id_estudo = sfa_paciente.id_estudo)")


def downgrade():
    # Não descartar silenciosamente o trabalho coletado após a migração.
    bind = op.get_bind()
    tables = ('sfa_acao', 'sfa_evento_vinculo', 'sfa_evento_coletivo', 'sfa_contato', 'sfa_contexto_episodio', 'sfa_resposta_t7')
    if any(bind.execute(sa.text(f'SELECT COUNT(*) FROM {table}')).scalar() for table in tables):
        raise RuntimeError('Há dados do novo fluxo SFA. Exporte e planeje a reversão antes de remover as tabelas.')
    for table in tables:
        op.drop_table(table)
    with op.batch_alter_table('sfa_paciente') as batch:
        batch.drop_column('data_t7')
        batch.drop_column('status_t7')
