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
    """Quarteirão escolhido para o casa a casa de um dia.

    Uma linha por quarteirão e dia. Fica em aberto até alguém concluir. Quem
    registra visita em quarteirão sem plano aberto cria a linha sozinho, de modo
    que todo quarteirão trabalhado tem a sua.
    """
    __tablename__ = "entomologia_quarteirao_trabalho"
    __table_args__ = (
        db.UniqueConstraint("bloco", "data", name="uq_entomologia_quarteirao_dia"),
    )

    id = db.Column(db.Integer, primary_key=True)
    bloco = db.Column(db.String(40), nullable=False, index=True)   # source_id na malha de quarteirões
    setor = db.Column(db.String(20), nullable=False)
    quarteirao = db.Column(db.String(20), nullable=False)
    data = db.Column(db.Date, nullable=False, index=True)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    responsavel = db.Column(db.String(160))
    concluido_em = db.Column(db.DateTime(timezone=True))
    concluido_por = db.Column(db.String(160))
    concluido_por_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    criado_por = db.Column(db.String(160), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    atualizado_em = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class EntomologiaVisitaDomiciliar(db.Model):
    """Visita a um imóvel no casa a casa, com os campos do boletim oficial "Visita a Imóvel".

    Uma visita não é alterada depois de gravada: corrigir é registrar outra, e
    vale a mais recente de cada imóvel. ``uuid_local`` vem do aparelho e torna o
    envio repetível (o modo sem internet reenvia até ter confirmação).
    """
    __tablename__ = "entomologia_visita_domiciliar"
    __table_args__ = (
        db.UniqueConstraint("uuid_local", name="uq_entomologia_visita_uuid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    uuid_local = db.Column(db.String(64), nullable=False, index=True)
    bloco = db.Column(db.String(40), nullable=False, index=True)
    setor = db.Column(db.String(20), nullable=False)
    quarteirao = db.Column(db.String(20), nullable=False)
    # Endereço na base do atlas ou, para imóvel acrescentado em campo, "novo-<uuid>".
    imovel = db.Column(db.String(80), nullable=False, index=True)
    logradouro = db.Column(db.String(200))
    numero = db.Column(db.String(50))
    complemento = db.Column(db.String(80))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    situacao = db.Column(db.String(20), nullable=False)   # services.entomologia_casa_a_casa.SITUACOES
    recipientes_existentes = db.Column(db.Integer, nullable=False, default=0)
    recipientes_agua = db.Column(db.Integer, nullable=False, default=0)
    recipientes_larva = db.Column(db.Integer, nullable=False, default=0)
    # Recipientes por tipo da ficha do SISAWEB (1 a 40): [{"t": 12, "e": 3, "a": 2, "l": 1}]. Vazio = só os totais.
    recipientes_json = db.Column(db.Text)
    larvas_encontradas = db.Column(db.Boolean, nullable=False, default=False)
    tubitos = db.Column(db.Integer, nullable=False, default=0)
    controle_mecanico = db.Column(db.Boolean, nullable=False, default=False)
    controle_alternativo = db.Column(db.Boolean, nullable=False, default=False)
    tratamento_focal = db.Column(db.Boolean, nullable=False, default=False)
    # Pendência anterior (fechado, recusa, temporada) resolvida por esta visita.
    recuperacao = db.Column(db.Boolean, nullable=False, default=False)
    observacao = db.Column(db.Text)
    agente_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    agente = db.Column(db.String(160))
    data_visita = db.Column(db.Date, nullable=False, index=True)
    horario_visita = db.Column(db.DateTime(timezone=True))
    recebido_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
