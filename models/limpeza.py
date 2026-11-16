"""Limpeza urbana: comunicações da população e comprovação da equipe contratada.

Cada comunicação guarda a foto, o ponto (latitude/longitude) e a hora em que
chegou ao servidor. A equipe de limpeza comprova o serviço com outra foto
tirada no local; a distância entre os dois pontos fica gravada para a
fiscalização do contrato. Nada é apagado: comprovação recusada e comunicação
descartada continuam no histórico, com quem fez e quando.
"""
from __future__ import annotations

from extensions import db
from time_utils import utcnow


class LimpezaAcesso(db.Model):
    """Papel adicional na área de limpeza urbana; não altera ``User.role``.

    ``papel``: ``colaborador`` (comunica), ``equipe`` (vê o mapa e comprova)
    ou ``fiscal`` (vê o mapa, recusa comprovações e exporta). ``inicio`` e
    ``fim`` (datas locais, inclusivas) limitam o período em que vale. ``tipos``
    restringe equipe e fiscalização a alguns tipos de problema.
    """
    __tablename__ = "limpeza_acesso"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    papel = db.Column(db.String(20), nullable=False)
    inicio = db.Column(db.Date)
    fim = db.Column(db.Date)
    # Tipos de problema (chaves de ``LimpezaTipo``) que a pessoa vê no mapa, comprova
    # e fiscaliza, separados por vírgula. Vazio = todos os tipos.
    tipos = db.Column(db.String(300))
    # Nome do perfil usado ao conceder (só para leitura na tela; o perfil é um modelo).
    perfil = db.Column(db.String(80))
    concedido_por = db.Column(db.String(160), nullable=False)
    concedido_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    revogado_em = db.Column(db.DateTime(timezone=True))
    revogado_por = db.Column(db.String(160))

    user = db.relationship("User", foreign_keys=[user_id])

    @property
    def lista_tipos(self):
        return [t for t in (self.tipos or "").split(",") if t]


class LimpezaTipo(db.Model):
    """Tipo de problema que a população marca ao comunicar. Cadastrado pelo administrador.

    Nunca é apagado: desativado, some da tela de comunicar e continua nomeando o histórico.
    """
    __tablename__ = "limpeza_tipo"

    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(30), unique=True, nullable=False)
    rotulo = db.Column(db.String(80), nullable=False)
    ordem = db.Column(db.Integer, nullable=False, default=0)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_por = db.Column(db.String(160))
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class LimpezaPapel(db.Model):
    """Papel criado pelo administrador: o que a pessoa pode fazer e quais tipos vê.

    ``chave`` é o que ``LimpezaAcesso.papel`` guarda. Excluir desativa o papel
    (e revoga os acessos dele); a linha fica para o histórico.
    """
    __tablename__ = "limpeza_papel"

    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(20), unique=True, nullable=False)
    nome = db.Column(db.String(80), nullable=False)
    # comunicar, mapa, comprovar, recusar, descartar, exportar — separados por vírgula.
    permissoes = db.Column(db.String(120), nullable=False)
    # Tipos que vê no mapa (chaves de ``LimpezaTipo``); vazio = todos.
    tipos = db.Column(db.String(300))
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_por = db.Column(db.String(160))
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class LimpezaPerfil(db.Model):
    """Combinação salva de papéis e tipos ("Equipe de poda") para atribuir com um clique."""
    __tablename__ = "limpeza_perfil"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), nullable=False)
    papeis = db.Column(db.String(60), nullable=False)
    tipos = db.Column(db.String(300))
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_por = db.Column(db.String(160))
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    @property
    def lista_papeis(self):
        return [p for p in (self.papeis or "").split(",") if p]

    @property
    def lista_tipos(self):
        return [t for t in (self.tipos or "").split(",") if t]


class LimpezaSolicitacao(db.Model):
    __tablename__ = "limpeza_solicitacao"

    id = db.Column(db.Integer, primary_key=True)
    autor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    chave_envio = db.Column(db.String(36), unique=True, nullable=True)
    # Um ou mais tipos (chaves de ``services.limpeza_urbana.CATEGORIAS``) separados por vírgula.
    categorias = db.Column(db.String(300), nullable=False)
    descricao = db.Column(db.String(500))
    referencia = db.Column(db.String(200))
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    precisao_m = db.Column(db.Float)
    # 'aparelho' (GPS do navegador na hora do envio) ou 'foto' (EXIF da imagem).
    origem_local = db.Column(db.String(12), nullable=False)
    foto_url = db.Column(db.String(500), nullable=False)
    foto_capturada_em = db.Column(db.DateTime(timezone=True))  # EXIF da câmera, convertido para UTC
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    # 'aberta', 'concluida' ou 'descartada'.
    status = db.Column(db.String(12), nullable=False, default="aberta", index=True)
    concluida_em = db.Column(db.DateTime(timezone=True))
    descartada_em = db.Column(db.DateTime(timezone=True))
    descartada_por = db.Column(db.String(160))
    motivo_descarte = db.Column(db.String(300))

    autor = db.relationship("User", foreign_keys=[autor_id])
    comprovacoes = db.relationship(
        "LimpezaComprovacao", back_populates="solicitacao",
        order_by="LimpezaComprovacao.criado_em", cascade="all, delete-orphan",
    )

    @property
    def lista_categorias(self):
        return [c for c in (self.categorias or "").split(",") if c]

    @property
    def comprovacao_valida(self):
        for item in reversed(self.comprovacoes):
            if item.status == "valida":
                return item
        return None


class LimpezaComprovacao(db.Model):
    __tablename__ = "limpeza_comprovacao"

    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey("limpeza_solicitacao.id"), nullable=False, index=True)
    autor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    observacao = db.Column(db.String(500))
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    precisao_m = db.Column(db.Float)
    origem_local = db.Column(db.String(12), nullable=False)
    distancia_m = db.Column(db.Float)
    foto_url = db.Column(db.String(500), nullable=False)
    foto_capturada_em = db.Column(db.DateTime(timezone=True))
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    # 'valida' ou 'recusada' (pela fiscalização; a comunicação volta a ficar aberta).
    status = db.Column(db.String(12), nullable=False, default="valida")
    recusada_em = db.Column(db.DateTime(timezone=True))
    recusada_por = db.Column(db.String(160))
    motivo_recusa = db.Column(db.String(300))

    solicitacao = db.relationship("LimpezaSolicitacao", back_populates="comprovacoes")
    autor = db.relationship("User", foreign_keys=[autor_id])


class LimpezaEvento(db.Model):
    """Trilha de auditoria: o que aconteceu, quem fez e quando."""
    __tablename__ = "limpeza_evento"

    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey("limpeza_solicitacao.id"), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    tipo = db.Column(db.String(30), nullable=False)
    detalhe = db.Column(db.String(500))
    criado_em = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
