"""Grupos de simulação com voluntários, separados da coorte municipal."""
from alembic import op
import sqlalchemy as sa

revision = 'f2c7a9d41b3e'
down_revision = 'f1e7a3c9b2d4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sfa_simulacao_grupo',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('nome', sa.String(120), nullable=False),
        sa.Column('descricao', sa.Text(), nullable=False, server_default=''),
        sa.Column('token_convite', sa.String(64), nullable=False, unique=True),
        sa.Column('creation_key', sa.String(64), nullable=False, unique=True),
        sa.Column('etapas', sa.String(40), nullable=False, server_default='sinan,t0,t7,t30'),
        sa.Column('agenda', sa.String(20), nullable=False, server_default='imediata'),
        sa.Column('cenarios_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(20), nullable=False, server_default='aberto'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('sfa_simulacao_participante',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('grupo_id', sa.Integer(), sa.ForeignKey('sfa_simulacao_grupo.id'), nullable=False),
        sa.Column('codigo', sa.String(12), nullable=False),
        sa.Column('apelido', sa.String(60), nullable=False, server_default=''),
        sa.Column('perfil', sa.String(60), nullable=False, server_default=''),
        sa.Column('experiencia_sinan', sa.String(60), nullable=False, server_default=''),
        sa.Column('token', sa.String(64), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('grupo_id', 'codigo', name='uq_sfa_simulacao_participante_codigo'))
    op.create_index('ix_sfa_simulacao_participante_grupo_id', 'sfa_simulacao_participante', ['grupo_id'])
    op.create_table('sfa_simulacao_resposta',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('participante_id', sa.Integer(), sa.ForeignKey('sfa_simulacao_participante.id'), nullable=False),
        sa.Column('etapa', sa.String(10), nullable=False),
        sa.Column('respostas_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('avaliacao_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('erros_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('instrument_version', sa.String(80), nullable=False, server_default=''),
        sa.Column('iniciado_em', sa.DateTime(timezone=True)),
        sa.Column('enviado_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duracao_segundos', sa.Integer()),
        sa.UniqueConstraint('participante_id', 'etapa', name='uq_sfa_simulacao_resposta_etapa'))
    op.create_index('ix_sfa_simulacao_resposta_participante_id', 'sfa_simulacao_resposta', ['participante_id'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM sfa_simulacao_resposta')).scalar():
        raise RuntimeError('Existem respostas de simulação. Exporte os dados antes de planejar a reversão.')
    op.drop_table('sfa_simulacao_resposta')
    op.drop_table('sfa_simulacao_participante')
    op.drop_table('sfa_simulacao_grupo')
