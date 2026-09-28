"""Arquivos de campo enviados pela equipe e boletins aprovados para a população.

A fotografia versionada em ``services/data/entomologia`` continua sendo a base.
Cada importação guarda apenas os campos não identificadores já usados pelo
painel; LOGIN e AGENTE do arquivo original nunca chegam ao banco.
"""
from __future__ import annotations

from extensions import db
from time_utils import utcnow


class EntomologiaImportacao(db.Model):
    """Um arquivo enviado: visitas (CSV/ZIP) ou camada de mapa (KML/KMZ).

    status: PREVIA (aguardando conferência), ATIVA (em uso) ou DESFEITA.
    Visitas ativas substituem, na base consolidada, os dias que contêm.
    """
    __tablename__ = "entomologia_importacao"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="PREVIA", index=True)
    nome_arquivo = db.Column(db.String(200), nullable=False)
    titulo = db.Column(db.String(200))
    sha256 = db.Column(db.String(64), nullable=False, index=True)
    inicio = db.Column(db.Date)
    fim = db.Column(db.Date)
    linhas = db.Column(db.Integer, nullable=False, default=0)
    resumo_json = db.Column(db.Text)
    dados_json = db.Column(db.Text, nullable=False)
    responsavel = db.Column(db.String(160), nullable=False)
    ator = db.Column(db.String(160))
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    confirmado_em = db.Column(db.DateTime(timezone=True))
    desfeito_em = db.Column(db.DateTime(timezone=True))
    desfeito_por = db.Column(db.String(160))


class EntomologiaPublicacao(db.Model):
    """Boletim agregado por setor, aprovado pela equipe antes de ficar público."""
    __tablename__ = "entomologia_publicacao"

    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), nullable=False, default="PUBLICADA", index=True)
    inicio = db.Column(db.Date, nullable=False)
    fim = db.Column(db.Date, nullable=False)
    dados_json = db.Column(db.Text, nullable=False)
    mensagem = db.Column(db.Text)
    contato = db.Column(db.String(300))
    assinatura = db.Column(db.String(200))
    responsavel = db.Column(db.String(160), nullable=False)
    ator = db.Column(db.String(160))
    publicado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    retirado_em = db.Column(db.DateTime(timezone=True))
    retirado_por = db.Column(db.String(160))


class EntomologiaEquipe(db.Model):
    """Papel adicional "Combate à dengue": não altera ``User.role``.

    Uma conta pode ser vacinador, tutor ou parceiro e, além disso, fazer parte
    da equipe de combate à dengue. Acesso ativo = ``revogado_em`` vazio.
    """
    __tablename__ = "entomologia_equipe"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    concedido_por = db.Column(db.String(160), nullable=False)
    concedido_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    revogado_em = db.Column(db.DateTime(timezone=True))
    revogado_por = db.Column(db.String(160))

    user = db.relationship("User", foreign_keys=[user_id])
