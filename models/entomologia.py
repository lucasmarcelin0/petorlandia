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


class EntomologiaAtlasArtefato(db.Model):
    """Saídas do atlas calculadas uma vez por versão dos dados (índice de busca, geometrias de ruas).

    São derivadas das importações ativas e dos arquivos versionados: podem ser
    apagadas a qualquer momento e são refeitas sozinhas. ``corpo`` guarda o JSON
    já comprimido em gzip (``corpo_br``, em brotli), pronto para ir ao navegador sem recomprimir.
    """
    __tablename__ = "entomologia_atlas_artefato"
    __table_args__ = (
        db.UniqueConstraint("versao", "variante", "tipo", name="uq_entomologia_atlas_artefato"),
    )

    id = db.Column(db.Integer, primary_key=True)
    versao = db.Column(db.String(32), nullable=False, index=True)
    variante = db.Column(db.String(16), nullable=False)
    tipo = db.Column(db.String(80), nullable=False)
    corpo = db.Column(db.LargeBinary, nullable=False)
    corpo_br = db.Column(db.LargeBinary)        # mesma resposta em brotli (~40% menor), quando vale a pena
    etag = db.Column(db.String(40), nullable=False)
    formato = db.Column(db.String(40), nullable=False, default='')   # INDEX_FORMAT de quem gravou
    bytes_crus = db.Column(db.Integer, nullable=False, default=0)
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class EntomologiaQuarteiraoTrabalho(db.Model):
    """Estado de planejamento e trabalho dos quarteirões pela equipe de campo."""
    __tablename__ = "entomologia_quarteirao_trabalho"
    __table_args__ = (
        db.UniqueConstraint("setor", "quarteirao", "ciclo", name="uq_entomologia_quarteirao_ciclo"),
    )

    id = db.Column(db.Integer, primary_key=True)
    setor = db.Column(db.String(20), nullable=False, index=True)
    quarteirao = db.Column(db.String(20), nullable=False, index=True)
    ciclo = db.Column(db.String(40), nullable=False, default="vigente", index=True)
    cor = db.Column(db.String(30))
    responsavel = db.Column(db.String(160))
    status = db.Column(db.String(30), nullable=False, default="PLANEJADO", index=True)  # PLANEJADO, EM_ANDAMENTO, TRABALHADO
    trabalhado_em = db.Column(db.DateTime(timezone=True))
    atualizado_em = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class EntomologiaVisitaDomiciliar(db.Model):
    """Visita casa a casa registrada pelo agente (online ou sincronizada do modo offline)."""
    __tablename__ = "entomologia_visita_domiciliar"
    __table_args__ = (
        db.UniqueConstraint("uuid_local", name="uq_entomologia_visita_uuid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    uuid_local = db.Column(db.String(64), nullable=False, index=True)
    setor = db.Column(db.String(20), nullable=False, index=True)
    quarteirao = db.Column(db.String(20), nullable=False, index=True)
    logradouro = db.Column(db.String(200))
    numero = db.Column(db.String(50))
    cnefe_id = db.Column(db.String(100), index=True)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    situacao = db.Column(db.String(30), nullable=False, default="ABERTA")  # ABERTA, FECHADA, RECUSA, DESABITADO
    criadouros_json = db.Column(db.Text)  # lista JSON dos tipos de recipientes encontrados: ["A1", "B", ...]
    larvas_encontradas = db.Column(db.Boolean, nullable=False, default=False)
    larvas_quantidade_tubitos = db.Column(db.Integer, default=0)
    larvas_especie = db.Column(db.String(50))
    agente = db.Column(db.String(160))
    data_visita = db.Column(db.Date)
    horario_visita = db.Column(db.DateTime(timezone=True))
    observacao = db.Column(db.Text)
    sincronizado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

