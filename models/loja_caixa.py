"""Caixa da loja (PDV): sessões, vendas de balcão e movimentos de estoque.

Tabelas novas. A loja online continua com seus pedidos (``order``) e o
estoque simples de ``product``/``product_variant``; o caixa usa o mesmo
estoque e registra cada entrada e saída em ``loja_estoque_movimento``.
"""
from __future__ import annotations

try:
    from extensions import db
except ImportError:  # pragma: no cover
    from ..extensions import db

from time_utils import now_in_brazil


FORMAS_PAGAMENTO_CAIXA = {
    "01": "Dinheiro",
    "20": "PIX",
    "03": "Crédito",
    "04": "Débito",
    "05": "Fiado (crédito loja)",
    "99": "Outros",
}


UNIDADES_FRACIONADAS = {"KG", "G", "L", "ML", "M", "M2", "M3"}


class CaixaSessao(db.Model):
    __tablename__ = "loja_caixa_sessao"
    __table_args__ = (
        # Um caixa aberto por loja.
        db.Index(
            "uq_loja_caixa_sessao_aberta",
            "casa_de_racao_id",
            unique=True,
            postgresql_where=db.text("status = 'aberto'"),
            sqlite_where=db.text("status = 'aberto'"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(
        db.Integer, db.ForeignKey("casa_de_racao.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = db.Column(db.String(10), nullable=False, default="aberto", index=True)
    valor_abertura = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    aberto_por_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    aberto_em = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    valor_contado = db.Column(db.Numeric(12, 2), nullable=True)
    valor_esperado = db.Column(db.Numeric(12, 2), nullable=True)
    fechado_por_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    fechado_em = db.Column(db.DateTime(timezone=True), nullable=True)
    observacao = db.Column(db.String(255), nullable=True)

    casa_de_racao = db.relationship("CasaDeRacao")

    @property
    def diferenca(self):
        if self.valor_contado is None or self.valor_esperado is None:
            return None
        return self.valor_contado - self.valor_esperado


class CaixaMovimento(db.Model):
    """Sangria (retirada) ou suprimento (reforço de troco) do caixa."""

    __tablename__ = "loja_caixa_movimento"

    id = db.Column(db.Integer, primary_key=True)
    sessao_id = db.Column(
        db.Integer, db.ForeignKey("loja_caixa_sessao.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo = db.Column(db.String(12), nullable=False)
    valor = db.Column(db.Numeric(12, 2), nullable=False)
    motivo = db.Column(db.String(255), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)

    sessao = db.relationship("CaixaSessao", backref=db.backref("movimentos", lazy="dynamic", cascade="all, delete-orphan"))


class VendaBalcao(db.Model):
    __tablename__ = "loja_venda"
    __table_args__ = (
        # O caixa manda uma chave por venda: um reenvio (rede caiu, clique
        # duplo) devolve a mesma venda em vez de cobrar duas vezes.
        db.UniqueConstraint("casa_de_racao_id", "chave_cliente", name="uq_loja_venda_chave_cliente"),
    )

    id = db.Column(db.Integer, primary_key=True)
    chave_cliente = db.Column(db.String(40), nullable=True)
    casa_de_racao_id = db.Column(
        db.Integer, db.ForeignKey("casa_de_racao.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sessao_id = db.Column(
        db.Integer, db.ForeignKey("loja_caixa_sessao.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status = db.Column(db.String(12), nullable=False, default="concluida", index=True)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    desconto = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    troco = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    emitir_nfce = db.Column(db.Boolean, nullable=False, default=False)
    nfce_documento_id = db.Column(
        db.Integer, db.ForeignKey("nfce_documento.id", ondelete="SET NULL"), nullable=True, index=True
    )
    nfce_erro = db.Column(db.String(255), nullable=True)
    cancel_motivo = db.Column(db.String(255), nullable=True)
    cancelada_em = db.Column(db.DateTime(timezone=True), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)

    sessao = db.relationship("CaixaSessao", backref=db.backref("vendas", lazy="dynamic"))
    nfce = db.relationship("NfceDocumento")
    itens = db.relationship("VendaBalcaoItem", back_populates="venda", cascade="all, delete-orphan")
    pagamentos = db.relationship("VendaBalcaoPagamento", back_populates="venda", cascade="all, delete-orphan")


class VendaBalcaoItem(db.Model):
    __tablename__ = "loja_venda_item"

    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.Integer, db.ForeignKey("loja_venda.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="SET NULL"), nullable=True, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variant.id", ondelete="SET NULL"), nullable=True)
    codigo = db.Column(db.String(60), nullable=False)
    descricao = db.Column(db.String(160), nullable=False)
    unidade = db.Column(db.String(6), nullable=False, default="UN")
    quantidade = db.Column(db.Numeric(12, 4), nullable=False)
    preco_unitario = db.Column(db.Numeric(12, 4), nullable=False)
    desconto = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(12, 2), nullable=False)
    # Dados fiscais no momento da venda (a nota é montada com eles).
    gtin = db.Column(db.String(14), nullable=True)
    ncm = db.Column(db.String(10), nullable=True)
    cest = db.Column(db.String(7), nullable=True)
    cfop = db.Column(db.String(4), nullable=True)
    csosn = db.Column(db.String(3), nullable=True)
    origem = db.Column(db.String(1), nullable=True)

    venda = db.relationship("VendaBalcao", back_populates="itens")
    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")


class VendaBalcaoPagamento(db.Model):
    __tablename__ = "loja_venda_pagamento"

    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.Integer, db.ForeignKey("loja_venda.id", ondelete="CASCADE"), nullable=False, index=True)
    t_pag = db.Column(db.String(2), nullable=False)
    valor = db.Column(db.Numeric(12, 2), nullable=False)
    autorizacao = db.Column(db.String(40), nullable=True)

    venda = db.relationship("VendaBalcao", back_populates="pagamentos")

    @property
    def forma(self) -> str:
        return FORMAS_PAGAMENTO_CAIXA.get(self.t_pag, "Outros")


class EstoqueMovimento(db.Model):
    """Cada entrada ou saída de estoque da loja, com o saldo após o movimento."""

    __tablename__ = "loja_estoque_movimento"

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(
        db.Integer, db.ForeignKey("casa_de_racao.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variant.id", ondelete="SET NULL"), nullable=True)
    # venda_balcao | cancelamento_venda | entrada_nota | ajuste | inventario
    tipo = db.Column(db.String(24), nullable=False)
    quantidade = db.Column(db.Numeric(12, 4), nullable=False)
    saldo_apos = db.Column(db.Numeric(12, 4), nullable=True)
    custo_unitario = db.Column(db.Numeric(12, 4), nullable=True)
    referencia_tipo = db.Column(db.String(24), nullable=True)
    referencia_id = db.Column(db.Integer, nullable=True, index=True)
    observacao = db.Column(db.String(255), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)

    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")
