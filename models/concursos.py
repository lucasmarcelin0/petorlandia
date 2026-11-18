"""Simulados de concurso para a estagiária (easter egg da área de estudo).

O supervisor envia o PDF da prova e o gabarito; a estagiária marca as
respostas numa folha A–E ao lado do PDF e entrega. A tentativa guarda as
marcações (rascunho salvo a cada clique) e, na entrega, a nota. Só tabelas
novas ``concurso_*``; nenhuma tabela existente é alterada.
"""
from __future__ import annotations

import json

from extensions import db
from time_utils import utcnow

#: Letra usada no gabarito para questão anulada: vale ponto para todos.
ANULADA = "X"
ALTERNATIVAS = ("A", "B", "C", "D", "E")


class ConcursoProva(db.Model):
    __tablename__ = "concurso_prova"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    banca = db.Column(db.String(80))
    cargo = db.Column(db.String(120))
    ano = db.Column(db.Integer)
    total_questoes = db.Column(db.Integer, nullable=False)
    #: Uma letra por questão, na ordem (``A``–``E``; ``X`` anulada; ``-`` ainda sem gabarito).
    gabarito = db.Column(db.String(400), nullable=False)
    pdf_nome = db.Column(db.String(200))
    pdf_prova = db.deferred(db.Column(db.LargeBinary))
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_por_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    tentativas = db.relationship("ConcursoTentativa", backref="prova", lazy="dynamic",
                                 cascade="all, delete-orphan")

    @property
    def gabarito_completo(self):
        return "-" not in (self.gabarito or "-") and len(self.gabarito or "") == self.total_questoes

    def resposta_certa(self, numero):
        try:
            return self.gabarito[numero - 1]
        except (IndexError, TypeError):
            return "-"


class ConcursoTentativa(db.Model):
    __tablename__ = "concurso_tentativa"

    id = db.Column(db.Integer, primary_key=True)
    prova_id = db.Column(db.Integer, db.ForeignKey("concurso_prova.id", ondelete="CASCADE"), nullable=False,
                         index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    #: JSON ``{"1": "C", "2": "A"}`` com as marcações.
    respostas = db.Column(db.Text, nullable=False, default="{}")
    iniciada_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    atualizada_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    entregue_em = db.Column(db.DateTime(timezone=True))
    acertos = db.Column(db.Integer)

    user = db.relationship("User", foreign_keys=[user_id])

    @property
    def marcacoes(self):
        try:
            dados = json.loads(self.respostas or "{}")
        except (TypeError, ValueError):
            return {}
        return {int(k): v for k, v in dados.items() if str(k).isdigit() and v in ALTERNATIVAS}

    @marcacoes.setter
    def marcacoes(self, valor):
        self.respostas = json.dumps({str(k): v for k, v in sorted(valor.items())})

    @property
    def respondidas(self):
        return len(self.marcacoes)
