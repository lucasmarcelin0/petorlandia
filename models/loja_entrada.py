"""Entrada de mercadoria pela NF-e de compra (XML do fornecedor).

A nota é importada como rascunho, conferida item a item (vincular a um
produto da loja, criar produto novo ou ignorar) e só então lançada no
estoque. O vínculo fornecedor+código fica gravado para a próxima nota.
"""
from __future__ import annotations

from decimal import Decimal

try:
    from extensions import db
except ImportError:  # pragma: no cover
    from ..extensions import db

from time_utils import now_in_brazil


ENTRADA_STATUS_LABELS = {
    "rascunho": "Em conferência",
    "lancada": "Lançada no estoque",
    "estornada": "Estornada",
}


class LojaEntradaNota(db.Model):
    __tablename__ = "loja_entrada_nota"
    __table_args__ = (
        db.UniqueConstraint("casa_de_racao_id", "chave", name="uq_loja_entrada_nota_chave"),
    )

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(
        db.Integer, db.ForeignKey("casa_de_racao.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chave = db.Column(db.String(44), nullable=False)
    numero = db.Column(db.String(9), nullable=True)
    serie = db.Column(db.String(3), nullable=True)
    dh_emi = db.Column(db.String(32), nullable=True)
    fornecedor_cnpj = db.Column(db.String(14), nullable=True, index=True)
    fornecedor_nome = db.Column(db.String(160), nullable=True)
    valor_total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    protocolo = db.Column(db.String(20), nullable=True)
    autorizada = db.Column(db.Boolean, nullable=False, default=False)
    # upload | sefaz (download automático)
    origem = db.Column(db.String(12), nullable=False, default="upload")
    status = db.Column(db.String(12), nullable=False, default="rascunho", index=True)
    xml = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    lancada_em = db.Column(db.DateTime(timezone=True), nullable=True)
    lancada_por_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    estornada_em = db.Column(db.DateTime(timezone=True), nullable=True)

    itens = db.relationship(
        "LojaEntradaItem",
        back_populates="entrada",
        cascade="all, delete-orphan",
        order_by="LojaEntradaItem.n_item",
    )

    @property
    def status_label(self) -> str:
        return ENTRADA_STATUS_LABELS.get(self.status, self.status)


class LojaEntradaItem(db.Model):
    __tablename__ = "loja_entrada_item"

    id = db.Column(db.Integer, primary_key=True)
    entrada_id = db.Column(
        db.Integer, db.ForeignKey("loja_entrada_nota.id", ondelete="CASCADE"), nullable=False, index=True
    )
    n_item = db.Column(db.Integer, nullable=False)
    codigo_fornecedor = db.Column(db.String(60), nullable=False)
    descricao = db.Column(db.String(160), nullable=False)
    gtin = db.Column(db.String(14), nullable=True)
    gtin_trib = db.Column(db.String(14), nullable=True)
    ncm = db.Column(db.String(8), nullable=True)
    cest = db.Column(db.String(7), nullable=True)
    origem = db.Column(db.String(1), nullable=True)
    unidade_compra = db.Column(db.String(6), nullable=False, default="UN")
    quantidade_compra = db.Column(db.Numeric(14, 4), nullable=False)
    # Custo total do item já com desconto, frete, seguro, outras despesas, ST e IPI.
    valor_total = db.Column(db.Numeric(12, 2), nullable=False)
    # Conferência
    acao = db.Column(db.String(10), nullable=False, default="criar")  # vincular | criar | ignorar
    fator = db.Column(db.Numeric(12, 4), nullable=False, default=1)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="SET NULL"), nullable=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variant.id", ondelete="SET NULL"), nullable=True)
    preco_venda = db.Column(db.Numeric(12, 2), nullable=True)
    unidade_venda = db.Column(db.String(6), nullable=True)
    sugestao = db.Column(db.String(20), nullable=True)  # como o vínculo foi achado

    entrada = db.relationship("LojaEntradaNota", back_populates="itens")
    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")

    @property
    def quantidade_estoque(self) -> Decimal:
        return (Decimal(self.quantidade_compra or 0) * Decimal(self.fator or 1)).quantize(Decimal("0.0001"))

    @property
    def custo_unitario(self) -> Decimal:
        quantidade = self.quantidade_estoque
        if quantidade <= 0:
            return Decimal("0")
        return (Decimal(self.valor_total or 0) / quantidade).quantize(Decimal("0.0001"))


class LojaFornecedorProduto(db.Model):
    """De-para: código do produto no fornecedor → produto da loja."""

    __tablename__ = "loja_fornecedor_produto"
    __table_args__ = (
        db.UniqueConstraint(
            "casa_de_racao_id", "fornecedor_cnpj", "codigo_fornecedor", name="uq_loja_fornecedor_produto"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(
        db.Integer, db.ForeignKey("casa_de_racao.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fornecedor_cnpj = db.Column(db.String(14), nullable=False)
    codigo_fornecedor = db.Column(db.String(60), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variant.id", ondelete="SET NULL"), nullable=True)
    fator = db.Column(db.Numeric(12, 4), nullable=False, default=1)
    updated_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, onupdate=now_in_brazil)

    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")
