"""Marcelino Academy: curso de inglês dentro do PetOrlândia.

Recriado a partir do antigo app Django ``marcelinoacademylive`` (matérias,
lições de gramática, testes, respostas e comentários), sem a cobrança via
Stripe: o acesso do aluno é uma matrícula feita pelo administrador ou pelo
professor da matéria. Todas as tabelas começam com ``academy_`` e não tocam
em nenhuma tabela existente além de referenciar ``user.id``.
"""
from __future__ import annotations

from extensions import db
from time_utils import utcnow

TIPOS_QUESTAO = {
    "unica": "Escolha única",
    "multipla": "Múltipla escolha",
    "aberta": "Resposta aberta (corrigida pelo professor)",
}


class AcademyMateria(db.Model):
    """Matéria/turma (ex.: "Inglês básico"). Nunca é apagada: desativada, some da lista."""
    __tablename__ = "academy_materia"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    descricao = db.Column(db.Text)
    link_aula = db.Column(db.String(300))
    horario = db.Column(db.String(60))
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_por = db.Column(db.String(160))
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    licoes = db.relationship("AcademyLicao", backref="materia", lazy="dynamic",
                             order_by="AcademyLicao.ordem")


class AcademyVinculo(db.Model):
    """Quem é professor ou aluno de cada matéria. ``revogado_em`` encerra sem apagar."""
    __tablename__ = "academy_vinculo"

    id = db.Column(db.Integer, primary_key=True)
    materia_id = db.Column(db.Integer, db.ForeignKey("academy_materia.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    papel = db.Column(db.String(20), nullable=False)  # professor | aluno
    concedido_por = db.Column(db.String(160))
    concedido_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    revogado_em = db.Column(db.DateTime(timezone=True))
    revogado_por = db.Column(db.String(160))

    materia = db.relationship("AcademyMateria")
    user = db.relationship("User", foreign_keys=[user_id])


class AcademyLicao(db.Model):
    """Lição (a antiga "Grammar"): texto da aula e testes."""
    __tablename__ = "academy_licao"

    id = db.Column(db.Integer, primary_key=True)
    materia_id = db.Column(db.Integer, db.ForeignKey("academy_materia.id"), nullable=False, index=True)
    titulo = db.Column(db.String(150), nullable=False)
    conteudo = db.Column(db.Text)
    link_video = db.Column(db.String(300))
    ordem = db.Column(db.Integer, nullable=False, default=0)
    publicada = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    testes = db.relationship("AcademyTeste", backref="licao", lazy="dynamic", order_by="AcademyTeste.id")


class AcademyTeste(db.Model):
    """Teste de uma lição (o antigo "Quiz")."""
    __tablename__ = "academy_teste"

    id = db.Column(db.Integer, primary_key=True)
    licao_id = db.Column(db.Integer, db.ForeignKey("academy_licao.id"), nullable=False, index=True)
    nome = db.Column(db.String(150), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    questoes = db.relationship("AcademyQuestao", backref="teste", lazy="dynamic",
                               order_by="AcademyQuestao.ordem, AcademyQuestao.id")


class AcademyQuestao(db.Model):
    __tablename__ = "academy_questao"

    id = db.Column(db.Integer, primary_key=True)
    teste_id = db.Column(db.Integer, db.ForeignKey("academy_teste.id"), nullable=False, index=True)
    enunciado = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(10), nullable=False, default="unica")
    ordem = db.Column(db.Integer, nullable=False, default=0)
    ativa = db.Column(db.Boolean, nullable=False, default=True)

    opcoes = db.relationship("AcademyOpcao", backref="questao", order_by="AcademyOpcao.id",
                             cascade="all, delete-orphan")


class AcademyOpcao(db.Model):
    __tablename__ = "academy_opcao"

    id = db.Column(db.Integer, primary_key=True)
    questao_id = db.Column(db.Integer, db.ForeignKey("academy_questao.id"), nullable=False, index=True)
    texto = db.Column(db.String(300), nullable=False)
    correta = db.Column(db.Boolean, nullable=False, default=False)


class AcademyResposta(db.Model):
    """Resposta do aluno a uma questão (uma por aluno e questão).

    ``nota``: 1 certa, 0 errada, ``None`` aguardando correção (resposta aberta).
    ``opcoes`` guarda os textos escolhidos, para o histórico não mudar se o
    professor editar a questão depois.
    """
    __tablename__ = "academy_resposta"
    __table_args__ = (db.UniqueConstraint("questao_id", "user_id", name="uq_academy_resposta_questao_user"),)

    id = db.Column(db.Integer, primary_key=True)
    questao_id = db.Column(db.Integer, db.ForeignKey("academy_questao.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    opcoes = db.Column(db.Text)
    texto = db.Column(db.Text)
    nota = db.Column(db.Integer)
    observacao = db.Column(db.Text)
    corrigida_por = db.Column(db.String(160))
    corrigida_em = db.Column(db.DateTime(timezone=True))
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    questao = db.relationship("AcademyQuestao")
    user = db.relationship("User", foreign_keys=[user_id])


class AcademyComentario(db.Model):
    __tablename__ = "academy_comentario"

    id = db.Column(db.Integer, primary_key=True)
    licao_id = db.Column(db.Integer, db.ForeignKey("academy_licao.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    texto = db.Column(db.Text, nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
