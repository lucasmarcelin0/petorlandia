"""Adiciona internação, prescrição hospitalar e histórico de administrações.

Revision ID: a26c1022b001
Revises: f4c9a2d6b8e1
"""
from alembic import op
import sqlalchemy as sa

revision = 'a26c1022b001'
down_revision = 'f4c9a2d6b8e1'
branch_labels = None
depends_on = None


def _id():
    return sa.Column('id', sa.Integer(), primary_key=True)


def _fk(name, target, nullable=False):
    return sa.Column(name, sa.Integer(), sa.ForeignKey(target), nullable=nullable)


def _dt(name, nullable=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    op.create_table(
        'internacao', _id(),
        _fk('clinica_id', 'clinica.id'), _fk('animal_id', 'animal.id'),
        _fk('consulta_id', 'consulta.id', True),
        _fk('responsavel_id', 'user.id'), _fk('criado_por_id', 'user.id'),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('motivo', sa.Text(), nullable=False),
        sa.Column('leito', sa.String(100)), sa.Column('alergias', sa.Text()),
        sa.Column('observacoes', sa.Text()), sa.Column('peso_kg', sa.Numeric(10, 3)),
        _dt('iniciada_em', False), _dt('encerrada_em'),
        sa.Column('resumo_alta', sa.Text()), _fk('alta_por_id', 'user.id', True),
        sa.CheckConstraint("status IN ('ativa', 'alta')", name='ck_internacao_status'),
    )
    op.create_index('uq_internacao_ativa_animal_clinica', 'internacao', ['clinica_id', 'animal_id'],
                    unique=True, postgresql_where=sa.text("status = 'ativa'"),
                    sqlite_where=sa.text("status = 'ativa'"))
    op.create_index('ix_internacao_clinica_status', 'internacao', ['clinica_id', 'status'])
    op.create_table(
        'internacao_prescricao', _id(), _fk('internacao_id', 'internacao.id'),
        _fk('anterior_id', 'internacao_prescricao.id', True),
        sa.Column('versao', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('medicamento', sa.String(240), nullable=False),
        sa.Column('apresentacao', sa.String(240)),
        sa.Column('dose', sa.String(240), nullable=False),
        sa.Column('via', sa.String(100), nullable=False),
        sa.Column('modo', sa.String(20), nullable=False),
        sa.Column('intervalo_horas', sa.Numeric(10, 3)),
        sa.Column('horarios_fixos', sa.JSON()),
        sa.Column('intervalo_minimo_horas', sa.Numeric(10, 3)),
        sa.Column('max_doses_24h', sa.Integer()),
        _dt('inicio_em', False), _dt('fim_em', False),
        sa.Column('instrucoes', sa.Text()), sa.Column('indicacao_prn', sa.Text()),
        sa.Column('limites_prn', sa.Text()), _fk('criado_por_id', 'user.id'),
        _dt('criada_em', False), _dt('suspensa_em'),
        _fk('suspensa_por_id', 'user.id', True), sa.Column('motivo_suspensao', sa.Text()),
        sa.UniqueConstraint('anterior_id', name='uq_internacao_prescricao_sucessora'),
        sa.CheckConstraint("modo IN ('intervalo', 'fixos', 'unica', 'prn')", name='ck_internacao_prescricao_modo'),
        sa.CheckConstraint("status IN ('ativa', 'substituida', 'suspensa', 'encerrada')", name='ck_internacao_prescricao_status'),
    )
    op.create_index('ix_internacao_prescricao_status', 'internacao_prescricao', ['internacao_id', 'status'])
    op.create_table(
        'internacao_ocorrencia', _id(), _fk('internacao_id', 'internacao.id'),
        _fk('prescricao_id', 'internacao_prescricao.id'), _dt('prevista_para', False),
        sa.Column('status', sa.String(20), nullable=False), _dt('cancelada_em'),
        sa.Column('motivo_cancelamento', sa.String(100)),
        sa.UniqueConstraint('prescricao_id', 'prevista_para', name='uq_internacao_ocorrencia_horario'),
        sa.CheckConstraint("status IN ('pendente', 'administrada', 'omitida', 'cancelada')", name='ck_internacao_ocorrencia_status'),
    )
    op.create_index('ix_internacao_ocorrencia_plantao', 'internacao_ocorrencia', ['internacao_id', 'status', 'prevista_para'])
    op.create_table(
        'internacao_registro', _id(), _fk('internacao_id', 'internacao.id'),
        _fk('prescricao_id', 'internacao_prescricao.id'),
        _fk('ocorrencia_id', 'internacao_ocorrencia.id', True),
        sa.Column('acao', sa.String(20), nullable=False),
        sa.Column('resultado', sa.String(20), nullable=False),
        _dt('executada_em'), _dt('registrada_em', False), _fk('autor_id', 'user.id'),
        sa.Column('motivo', sa.Text()), sa.Column('observacoes', sa.Text()),
        sa.Column('idempotency_key', sa.String(100)),
        _fk('retifica_id', 'internacao_registro.id', True),
        sa.UniqueConstraint('internacao_id', 'idempotency_key', name='uq_internacao_registro_idempotencia'),
        sa.UniqueConstraint('retifica_id', name='uq_internacao_registro_retificacao'),
        sa.CheckConstraint("acao IN ('administracao', 'omissao', 'retificacao')", name='ck_internacao_registro_acao'),
        sa.CheckConstraint("resultado IN ('administrada', 'omitida', 'pendente')", name='ck_internacao_registro_resultado'),
    )
    op.create_index('ix_internacao_registro_prescricao', 'internacao_registro', ['prescricao_id', 'registrada_em'])
    op.create_table(
        'internacao_evolucao', _id(), _fk('internacao_id', 'internacao.id'),
        sa.Column('tipo', sa.String(20), nullable=False),
        sa.Column('texto', sa.Text(), nullable=False), sa.Column('pendencias', sa.Text()),
        sa.Column('parametros', sa.JSON()), _fk('autor_id', 'user.id'), _dt('criada_em', False),
    )
    op.create_index('ix_internacao_evolucao_internacao_id', 'internacao_evolucao', ['internacao_id'])
    op.create_table(
        'internacao_evento', _id(), _fk('internacao_id', 'internacao.id'),
        sa.Column('tipo', sa.String(40), nullable=False), sa.Column('dados', sa.JSON()),
        _fk('autor_id', 'user.id'), _dt('criado_em', False),
    )
    op.create_index('ix_internacao_evento_internacao_id', 'internacao_evento', ['internacao_id'])


def downgrade():
    op.drop_table('internacao_evento')
    op.drop_table('internacao_evolucao')
    op.drop_table('internacao_registro')
    op.drop_table('internacao_ocorrencia')
    op.drop_table('internacao_prescricao')
    op.drop_table('internacao')
