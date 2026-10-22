"""Prontuário hospitalar separado do acompanhamento domiciliar.

As ocorrências são a agenda operacional. Os registros e eventos constituem o
histórico: correções acrescentam novos registros, nunca sobrescrevem a autoria.
"""
from sqlalchemy import event

from extensions import db
from time_utils import utcnow


class Internacao(db.Model):
    __tablename__ = 'internacao'
    __table_args__ = (
        db.Index('uq_internacao_ativa_animal_clinica', 'clinica_id', 'animal_id',
                 unique=True, postgresql_where=db.text("status = 'ativa'"),
                 sqlite_where=db.text("status = 'ativa'")),
        db.Index('ix_internacao_clinica_status', 'clinica_id', 'status'),
        db.CheckConstraint("status IN ('ativa', 'alta')", name='ck_internacao_status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    consulta_id = db.Column(db.Integer, db.ForeignKey('consulta.id'))
    responsavel_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    criado_por_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='ativa')
    motivo = db.Column(db.Text, nullable=False)
    leito = db.Column(db.String(100))
    alergias = db.Column(db.Text)
    observacoes = db.Column(db.Text)
    peso_kg = db.Column(db.Numeric(10, 3))
    iniciada_em = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    encerrada_em = db.Column(db.DateTime(timezone=True))
    resumo_alta = db.Column(db.Text)
    alta_por_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    animal = db.relationship('Animal', backref='internacoes')
    clinica = db.relationship('Clinica')
    consulta = db.relationship('Consulta')
    responsavel = db.relationship('User', foreign_keys=[responsavel_id])
    criado_por = db.relationship('User', foreign_keys=[criado_por_id])
    alta_por = db.relationship('User', foreign_keys=[alta_por_id])
    prescricoes = db.relationship('InternacaoPrescricao', back_populates='internacao', order_by='InternacaoPrescricao.id')
    ocorrencias = db.relationship('InternacaoOcorrencia', back_populates='internacao', order_by='InternacaoOcorrencia.prevista_para')
    registros = db.relationship('InternacaoRegistro', back_populates='internacao', order_by='InternacaoRegistro.registrada_em')
    evolucoes = db.relationship('InternacaoEvolucao', back_populates='internacao', order_by='InternacaoEvolucao.criada_em')
    eventos = db.relationship('InternacaoEvento', back_populates='internacao', order_by='InternacaoEvento.criado_em')


class InternacaoPrescricao(db.Model):
    __tablename__ = 'internacao_prescricao'
    __table_args__ = (
        db.Index('ix_internacao_prescricao_status', 'internacao_id', 'status'),
        db.UniqueConstraint('anterior_id', name='uq_internacao_prescricao_sucessora'),
        db.CheckConstraint("modo IN ('intervalo', 'fixos', 'unica', 'prn')", name='ck_internacao_prescricao_modo'),
        db.CheckConstraint("status IN ('ativa', 'substituida', 'suspensa', 'encerrada')", name='ck_internacao_prescricao_status'),
    )
    id = db.Column(db.Integer, primary_key=True)
    internacao_id = db.Column(db.Integer, db.ForeignKey('internacao.id'), nullable=False)
    anterior_id = db.Column(db.Integer, db.ForeignKey('internacao_prescricao.id'))
    versao = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default='ativa')
    medicamento = db.Column(db.String(240), nullable=False)
    apresentacao = db.Column(db.String(240))
    dose = db.Column(db.String(240), nullable=False)
    via = db.Column(db.String(100), nullable=False)
    modo = db.Column(db.String(20), nullable=False)
    intervalo_horas = db.Column(db.Numeric(10, 3))
    horarios_fixos = db.Column(db.JSON)
    intervalo_minimo_horas = db.Column(db.Numeric(10, 3))
    max_doses_24h = db.Column(db.Integer)
    inicio_em = db.Column(db.DateTime(timezone=True), nullable=False)
    fim_em = db.Column(db.DateTime(timezone=True), nullable=False)
    instrucoes = db.Column(db.Text)
    indicacao_prn = db.Column(db.Text)
    limites_prn = db.Column(db.Text)
    criado_por_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    criada_em = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    suspensa_em = db.Column(db.DateTime(timezone=True))
    suspensa_por_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    motivo_suspensao = db.Column(db.Text)

    internacao = db.relationship('Internacao', back_populates='prescricoes')
    anterior = db.relationship('InternacaoPrescricao', remote_side=[id], foreign_keys=[anterior_id])
    criado_por = db.relationship('User', foreign_keys=[criado_por_id])
    suspensa_por = db.relationship('User', foreign_keys=[suspensa_por_id])
    ocorrencias = db.relationship('InternacaoOcorrencia', back_populates='prescricao', order_by='InternacaoOcorrencia.prevista_para')


class InternacaoOcorrencia(db.Model):
    __tablename__ = 'internacao_ocorrencia'
    __table_args__ = (
        db.UniqueConstraint('prescricao_id', 'prevista_para', name='uq_internacao_ocorrencia_horario'),
        db.Index('ix_internacao_ocorrencia_plantao', 'internacao_id', 'status', 'prevista_para'),
        db.CheckConstraint("status IN ('pendente', 'administrada', 'omitida', 'cancelada')", name='ck_internacao_ocorrencia_status'),
    )
    id = db.Column(db.Integer, primary_key=True)
    internacao_id = db.Column(db.Integer, db.ForeignKey('internacao.id'), nullable=False)
    prescricao_id = db.Column(db.Integer, db.ForeignKey('internacao_prescricao.id'), nullable=False)
    prevista_para = db.Column(db.DateTime(timezone=True), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pendente')
    cancelada_em = db.Column(db.DateTime(timezone=True))
    motivo_cancelamento = db.Column(db.String(100))
    internacao = db.relationship('Internacao', back_populates='ocorrencias')
    prescricao = db.relationship('InternacaoPrescricao', back_populates='ocorrencias')
    registros = db.relationship('InternacaoRegistro', back_populates='ocorrencia', order_by='InternacaoRegistro.id')


class InternacaoRegistro(db.Model):
    __tablename__ = 'internacao_registro'
    __table_args__ = (
        db.UniqueConstraint('internacao_id', 'idempotency_key', name='uq_internacao_registro_idempotencia'),
        db.UniqueConstraint('retifica_id', name='uq_internacao_registro_retificacao'),
        db.Index('ix_internacao_registro_prescricao', 'prescricao_id', 'registrada_em'),
        db.CheckConstraint("acao IN ('administracao', 'omissao', 'retificacao')", name='ck_internacao_registro_acao'),
        db.CheckConstraint("resultado IN ('administrada', 'omitida', 'pendente')", name='ck_internacao_registro_resultado'),
    )
    id = db.Column(db.Integer, primary_key=True)
    internacao_id = db.Column(db.Integer, db.ForeignKey('internacao.id'), nullable=False)
    prescricao_id = db.Column(db.Integer, db.ForeignKey('internacao_prescricao.id'), nullable=False)
    ocorrencia_id = db.Column(db.Integer, db.ForeignKey('internacao_ocorrencia.id'))
    acao = db.Column(db.String(20), nullable=False)
    resultado = db.Column(db.String(20), nullable=False)
    executada_em = db.Column(db.DateTime(timezone=True))
    registrada_em = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    autor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    motivo = db.Column(db.Text)
    observacoes = db.Column(db.Text)
    idempotency_key = db.Column(db.String(100))
    retifica_id = db.Column(db.Integer, db.ForeignKey('internacao_registro.id'))
    internacao = db.relationship('Internacao', back_populates='registros')
    prescricao = db.relationship('InternacaoPrescricao')
    ocorrencia = db.relationship('InternacaoOcorrencia', back_populates='registros')
    autor = db.relationship('User', foreign_keys=[autor_id])
    retifica = db.relationship('InternacaoRegistro', remote_side=[id], foreign_keys=[retifica_id])


class InternacaoEvolucao(db.Model):
    __tablename__ = 'internacao_evolucao'
    id = db.Column(db.Integer, primary_key=True)
    internacao_id = db.Column(db.Integer, db.ForeignKey('internacao.id'), nullable=False, index=True)
    tipo = db.Column(db.String(20), nullable=False, default='evolucao')
    texto = db.Column(db.Text, nullable=False)
    pendencias = db.Column(db.Text)
    parametros = db.Column(db.JSON)
    autor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    criada_em = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    internacao = db.relationship('Internacao', back_populates='evolucoes')
    autor = db.relationship('User', foreign_keys=[autor_id])


class InternacaoEvento(db.Model):
    __tablename__ = 'internacao_evento'
    id = db.Column(db.Integer, primary_key=True)
    internacao_id = db.Column(db.Integer, db.ForeignKey('internacao.id'), nullable=False, index=True)
    tipo = db.Column(db.String(40), nullable=False)
    dados = db.Column(db.JSON)
    autor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    internacao = db.relationship('Internacao', back_populates='eventos')
    autor = db.relationship('User', foreign_keys=[autor_id])


def _historico_imutavel(_mapper, _connection, _target):
    raise ValueError('Histórico de internação é imutável; acrescente uma retificação.')


for _model in (InternacaoRegistro, InternacaoEvolucao, InternacaoEvento):
    event.listen(_model, 'before_update', _historico_imutavel)
    event.listen(_model, 'before_delete', _historico_imutavel)
