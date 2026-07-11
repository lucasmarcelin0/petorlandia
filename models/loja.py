"""Loja: produtos, pedidos, entregas e pagamentos.

Extraído de models/base.py na modularização (2026-07-10).
"""
try:
    from extensions import db
except ImportError:
    from .extensions import db

from flask_login import UserMixin
from flask import url_for, request, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta, timezone
import json
from dateutil.relativedelta import relativedelta
from decimal import Decimal, ROUND_CEILING
import unicodedata
import enum
import uuid
from sqlalchemy import Enum, event, func, case, inspect
from enum import Enum
from sqlalchemy import Enum as PgEnum
from sqlalchemy.orm import synonym, object_session, deferred, validates
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.exc import OperationalError, ProgrammingError
from cryptography.fernet import InvalidToken
from functools import lru_cache
try:
    from document_utils import format_cnpj
except ImportError:
    from ..document_utils import format_cnpj
from time_utils import utcnow, now_in_brazil
from security.crypto import (
    MissingMasterKeyError,
    decrypt_text,
    decrypt_text_for_clinic,
    encrypt_text,
    looks_encrypted_text,
)




class Transaction(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    from_user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    to_user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    type = db.Column(db.String(20))  # adoção, doação, venda, compra
    date = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    status = db.Column(db.String(20))  # pendente, concluída, cancelada

    from_user = db.relationship(
        'User',
        foreign_keys=[from_user_id],
        backref=db.backref('transacoes_enviadas', cascade='all, delete-orphan'),
    )
    to_user = db.relationship(
        'User',
        foreign_keys=[to_user_id],
        backref=db.backref('transacoes_recebidas', cascade='all, delete-orphan'),
    )


class DeliveryResearchContact(db.Model):
    __tablename__ = 'delivery_research_contact'

    id = db.Column(db.Integer, primary_key=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, unique=True, index=True)
    sent = db.Column(db.Boolean, nullable=False, default=False)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    sent_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    replied = db.Column(db.Boolean, nullable=False, default=False)
    replied_at = db.Column(db.DateTime(timezone=True), nullable=True)
    replied_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    recorded = db.Column(db.Boolean, nullable=False, default=False)
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    do_not_send = db.Column(db.Boolean, nullable=False, default=False)
    do_not_send_at = db.Column(db.DateTime(timezone=True), nullable=True)
    do_not_send_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    interest_answer = db.Column(db.String(20), nullable=True)
    current_food = db.Column(db.String(255), nullable=True)
    bag_size = db.Column(db.String(80), nullable=True)
    price_paid = db.Column(db.String(80), nullable=True)
    purchase_channel = db.Column(db.String(120), nullable=True)
    duration_estimate = db.Column(db.String(120), nullable=True)
    response_notes = db.Column(db.Text, nullable=True)
    response_collected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    tutor = db.relationship('User', foreign_keys=[tutor_id], backref=db.backref('delivery_research_contact', uselist=False, cascade='all, delete-orphan'))
    sent_by = db.relationship('User', foreign_keys=[sent_by_id])
    replied_by = db.relationship('User', foreign_keys=[replied_by_id])
    recorded_by = db.relationship('User', foreign_keys=[recorded_by_id])
    do_not_send_by = db.relationship('User', foreign_keys=[do_not_send_by_id])


PRODUCT_CATEGORIES = [
    {"value": "racao",       "label": "Ração",            "icon": "fa-bowl-food"},
    {"value": "petisco",     "label": "Petiscos",         "icon": "fa-bone"},
    {"value": "brinquedo",   "label": "Brinquedos",       "icon": "fa-baseball"},
    {"value": "higiene",     "label": "Higiene & Beleza", "icon": "fa-pump-soap"},
    {"value": "acessorio",   "label": "Acessórios",       "icon": "fa-tag"},
    {"value": "medicamento", "label": "Medicamentos",     "icon": "fa-pills"},
]


PRODUCT_CATEGORY_VALUES = [c["value"] for c in PRODUCT_CATEGORIES]


PRODUCT_CATEGORY_LABELS = {c["value"]: c["label"] for c in PRODUCT_CATEGORIES}
# Opções para SelectField, com entrada vazia para "sem categoria".


PRODUCT_CATEGORY_CHOICES = [("", "— Sem categoria —")] + [
    (c["value"], c["label"]) for c in PRODUCT_CATEGORIES
]


class ProductCategory(db.Model):
    """Categoria de produto da Loja — gerenciável pelo admin.

    Substitui a antiga lista fixa em código: novas categorias podem ser
    adicionadas conforme a necessidade pelo painel administrativo. A constante
    ``PRODUCT_CATEGORIES`` permanece apenas como semente inicial desta tabela
    (e como fallback caso a tabela ainda não exista / esteja vazia).
    """
    __tablename__ = "product_category"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(40), unique=True, nullable=False)
    label = db.Column(db.String(60), nullable=False)
    icon = db.Column(db.String(40), default="fa-tag")
    position = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True, nullable=False)

    @property
    def value(self):
        """Alias usado pelos templates de chips (mesma semântica do slug)."""
        return self.slug

    def __str__(self):
        return self.label or self.slug

    def __repr__(self):
        return f"<ProductCategory {self.slug}>"


def _seed_product_categories():
    """Categorias semente como objetos transitórios (não persistidos).

    Usado como fallback quando a tabela ``product_category`` ainda não existe
    (antes da migração) ou está vazia, garantindo que a Loja nunca quebre.
    """
    return [
        ProductCategory(slug=c["value"], label=c["label"], icon=c["icon"],
                        position=i, active=True)
        for i, c in enumerate(PRODUCT_CATEGORIES)
    ]


def get_active_product_categories():
    """Categorias ativas, ordenadas para exibição (chips/select)."""
    try:
        cats = (
            ProductCategory.query
            .filter_by(active=True)
            .order_by(ProductCategory.position, ProductCategory.label)
            .all()
        )
    except Exception:
        # Tabela ainda não migrada: desfaz a transação abortada e usa a semente.
        try:
            db.session.rollback()
        except Exception:
            pass
        cats = []
    return cats or _seed_product_categories()


def product_category_choices():
    """Choices para SelectField, com entrada vazia para 'sem categoria'."""
    return [("", "— Sem categoria —")] + [
        (c.slug, c.label) for c in get_active_product_categories()
    ]


def product_category_map():
    """Mapa slug -> ProductCategory, cacheado por requisição (evita N+1)."""
    from flask import g, has_request_context
    if has_request_context():
        cached = getattr(g, "_product_category_map", None)
        if cached is not None:
            return cached
    mapping = {c.slug: c for c in get_active_product_categories()}
    if has_request_context():
        try:
            g._product_category_map = mapping
        except Exception:
            pass
    return mapping


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    image_url = db.Column(db.String(200))
    # Categoria de exibição na Loja (filtros/chips). Ver PRODUCT_CATEGORIES.
    category = db.Column(db.String(40), index=True)
    mp_category_id = db.Column(db.String(50), default="others")
    ncm = db.Column(db.String(10))
    cfop = db.Column(db.String(10))
    cst = db.Column(db.String(5))
    csosn = db.Column(db.String(5))
    origem = db.Column(db.String(2))
    unidade = db.Column(db.String(10))
    aliquota_icms = db.Column(db.Numeric(10, 4))
    aliquota_pis = db.Column(db.Numeric(10, 4))
    aliquota_cofins = db.Column(db.Numeric(10, 4))

    # Campos de venda por clínica
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id', ondelete='SET NULL'), nullable=True, index=True)
    clinic_inventory_item_id = db.Column(db.Integer, db.ForeignKey('clinic_inventory_item.id', ondelete='SET NULL'), nullable=True)
    # Vendedor alternativo: casa de ração parceira
    casa_de_racao_id = db.Column(db.Integer, db.ForeignKey('casa_de_racao.id', ondelete='SET NULL'), nullable=True, index=True)
    # 'active' = visível na loja, 'inactive' = oculto pelo dono, 'pending' = aguardando aprovação
    status = db.Column(db.String(20), default='active', nullable=False)

    clinica = db.relationship('Clinica', backref=db.backref('produtos_loja', lazy='dynamic'))
    inventory_item = db.relationship('ClinicInventoryItem', backref=db.backref('produto_loja', uselist=False))
    casa_de_racao = db.relationship('CasaDeRacao', backref=db.backref('produtos_loja', lazy='dynamic'))

    # Items de pedido associados ao produto. O cascade facilita remover os
    # OrderItem relacionados quando o produto é excluído.
    order_items = db.relationship(
        "OrderItem",
        back_populates="product",
        cascade="all, delete-orphan"
    )

    variants = db.relationship(
        "ProductVariant",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductVariant.position.asc(), ProductVariant.id.asc()",
    )

    @staticmethod
    def public_price_from_base(value):
        """Preço público a partir do preço recebido pelo lojista."""
        if value is None:
            return None
        base = Decimal(str(value))
        if base <= 0:
            return base.quantize(Decimal("0.01"))
        gross = base * Decimal("1.10")
        step = Decimal("5")
        steps = (gross / step).to_integral_value(rounding=ROUND_CEILING)
        return (steps * step).quantize(Decimal("0.01"))

    @property
    def preco_publico(self):
        """Preço único exibido ao tutor, com a taxa da plataforma embutida.

        ``price`` é o valor que o lojista recebe. O preço público é
        ``price`` + 10%, arredondado PARA CIMA ao próximo múltiplo de
        R$ 5 — mesma regra de vacinas e serviços profissionais. A taxa
        nunca aparece separada para o comprador.
        """
        return self.public_price_from_base(self.price)

    @property
    def active_variants(self):
        """Variações vendáveis do produto, com fallback para produto legado."""
        return [
            variant for variant in (self.variants or [])
            if variant.status == "active"
        ]

    @property
    def default_variant(self):
        active = self.active_variants
        if active:
            return active[0]
        return None

    @property
    def has_variants(self):
        return bool(self.active_variants)

    @property
    def public_price_min(self):
        prices = [
            variant.preco_publico for variant in self.active_variants
            if variant.preco_publico is not None
        ]
        if prices:
            return min(prices)
        return self.preco_publico

    @property
    def public_price_max(self):
        prices = [
            variant.preco_publico for variant in self.active_variants
            if variant.preco_publico is not None
        ]
        if prices:
            return max(prices)
        return self.preco_publico

    @property
    def variant_count_label(self):
        count = len(self.active_variants)
        if count <= 1:
            return None
        return f"{count} apresentações disponíveis"

    @property
    def category_label(self):
        """Rótulo de exibição da categoria (ex.: 'racao' -> 'Ração')."""
        if not self.category:
            return None
        cat = product_category_map().get(self.category)
        return cat.label if cat else None

    @property
    def category_icon(self):
        """Ícone Font Awesome da categoria, com fallback genérico."""
        cat = product_category_map().get(self.category) if self.category else None
        return cat.icon if cat else "fa-tag"

    def __repr__(self):
        return f"{self.name} (R$ {self.price})"

    def __str__(self):
        return self.__repr__()


class ProductVariant(db.Model):
    """Apresentação/SKU vendável de um produto.

    Exemplos:
    - Simparic 10 mg — caixa com 3 comprimidos
    - Ração 15 kg
    """
    __tablename__ = "product_variant"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("product.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(160), nullable=False)
    dosage = db.Column(db.String(80), nullable=True)
    package_quantity = db.Column(db.String(80), nullable=True)
    weight_volume = db.Column(db.String(80), nullable=True)
    sku = db.Column(db.String(80), nullable=True)
    barcode = db.Column(db.String(80), nullable=True)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    image_url = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), default="active", nullable=False)
    position = db.Column(db.Integer, default=0, nullable=False)

    product = db.relationship("Product", back_populates="variants")
    order_items = db.relationship("OrderItem", back_populates="variant")

    @property
    def preco_publico(self):
        return Product.public_price_from_base(self.price)

    @property
    def display_name(self):
        parts = [self.name]
        extras = [value for value in (self.dosage, self.package_quantity, self.weight_volume) if value]
        if extras and not any(extra.lower() in (self.name or "").lower() for extra in extras):
            parts.append(" · ".join(extras))
        return " — ".join(parts)

    def __repr__(self):
        return f"{self.product.name if self.product else 'Produto'} / {self.name} (R$ {self.price})"


class ProductPhoto(db.Model):
    """Fotos adicionais para produtos."""
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    image_url = db.Column(db.String(200))

    product = db.relationship('Product', backref='extra_photos')


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    shipping_address = db.Column(db.String(200))
    # Confirmação do tutor de que o pedido chegou — base para liberar
    # repasses (entregador/lojista) com segurança.
    received_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # Último lembrete pedindo a confirmação de recebimento (evita spam diário).
    receipt_reminder_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship(
        'User',
        backref=db.backref('orders', cascade='all, delete-orphan')
    )
    items = db.relationship('OrderItem', backref='order', cascade='all, delete-orphan')




    def total_value(self):
        """Valor total do pedido pelo preço público (o que o comprador paga)."""
        total = 0.0
        for item in self.items:
            if item.unit_price is not None:
                total += float(item.unit_price) * item.quantity
            elif item.product:
                total += float(item.product.preco_publico or 0) * item.quantity
        return total

    def __str__(self):
        nome_usuario = self.user.name if self.user else "Usuário desconhecido"
        valor = self.total_value()
        return f"Pedido #{self.id} de {nome_usuario} - R$ {valor:.2f}"


class OrderItem(db.Model):
    __tablename__ = "order_item"

    id          = db.Column(db.Integer, primary_key=True)
    order_id    = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    product_id  = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    variant_id  = db.Column(db.Integer, db.ForeignKey("product_variant.id", ondelete="SET NULL"), nullable=True, index=True)
    # back_populates permite acesso recíproco a partir de Product.order_items
    product     = db.relationship("Product", back_populates="order_items")
    variant     = db.relationship("ProductVariant", back_populates="order_items")

    item_name   = db.Column(db.String(100), nullable=False)
    quantity    = db.Column(db.Integer, nullable=False, default=1)
    unit_price  = db.Column(db.Numeric(10, 2), nullable=True)   # NOVO 👈

    def __str__(self):
        return f"{self.product.name if self.product else self.item_name} x{self.quantity}"


class SavedAddress(db.Model):
    """Endereços extras salvos pelo usuário."""
    __tablename__ = 'saved_address'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    address = db.Column(db.String(200), nullable=False)

    # Delete saved addresses when the owning user is removed
    user = db.relationship(
        'User',
        backref=db.backref('saved_addresses', cascade='all, delete-orphan')
    )

    def __repr__(self):
        return self.address


class DeliveryRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    requested_by_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )
    requested_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    status = db.Column(db.String(20), default='pendente')
    worker_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
    )
    worker_latitude = db.Column(db.Float, nullable=True)
    worker_longitude = db.Column(db.Float, nullable=True)
    accepted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    canceled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    canceled_by_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
    )
    archived = db.Column(db.Boolean, default=False, nullable=False)
    # Deterministic idempotency key for one seller leg of one order. This
    # prevents duplicate delivery requests when payment webhooks race/retry.
    dedupe_key = db.Column(db.String(160), unique=True, nullable=True, index=True)
    # Vendedor responsável por esta entrega (apenas um dos dois estará preenchido)
    clinica_id = db.Column(db.Integer, db.ForeignKey('clinica.id', ondelete='SET NULL'), nullable=True, index=True)
    casa_de_racao_id = db.Column(db.Integer, db.ForeignKey('casa_de_racao.id', ondelete='SET NULL'), nullable=True, index=True)
    # 'plataforma' = fila de entregadores, 'propria' = vendedor gerencia
    tipo_entrega = db.Column(db.String(20), default='plataforma', nullable=False)

    # Repasse do frete ao entregador (entregas 'plataforma'): valor congelado
    # na conclusão da entrega; liberado quando o tutor confirma o recebimento
    # (order.received_at) e pago em lote semanal pelo admin.
    frete_valor = db.Column(db.Numeric(10, 2), nullable=True)
    frete_pago_em = db.Column(db.DateTime(timezone=True), nullable=True)
    frete_pago_por_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
    )

    order = db.relationship('Order', backref='delivery_requests')
    requested_by = db.relationship(
        'User',
        foreign_keys=[requested_by_id],
        backref=db.backref('delivery_requests_made', cascade='all, delete-orphan'),
    )
    worker = db.relationship('User', foreign_keys=[worker_id])
    canceled_by = db.relationship('User', foreign_keys=[canceled_by_id])
    pickup_id   = db.Column(db.Integer, db.ForeignKey('pickup_location.id'))
    pickup      = db.relationship('PickupLocation')
    clinica     = db.relationship('Clinica', foreign_keys=[clinica_id])
    casa_de_racao = db.relationship('CasaDeRacao', foreign_keys=[casa_de_racao_id],
                                    backref=db.backref('delivery_requests', lazy='dynamic'))

    def __str__(self):
        return f"Entrega #{self.id} - Pedido #{self.order_id} ({self.status})"


class PickupLocation(db.Model):
    __tablename__ = "pickup_location"
    id          = db.Column(db.Integer, primary_key=True)
    nome        = db.Column(db.String(120))           # “Galpão Central”, “Hub Ribeirão”…
    endereco_id = db.Column(db.Integer, db.ForeignKey('endereco.id'))
    endereco    = db.relationship('Endereco')
    ativo       = db.Column(db.Boolean, default=True) # permite desativar pontos


    endereco    = db.relationship(
        "Endereco",
        back_populates="pickup_location",
        uselist=False
    )


class PaymentMethod(Enum):
    PIX = 'PIX'
    CREDIT_CARD = 'Cartão de Crédito'
    DEBIT_CARD = 'Cartão de Débito'
    BOLETO = 'Boleto'


class PaymentStatus(Enum):
    PENDING = 'Pendente'
    COMPLETED = 'Concluído'
    FAILED = 'Falhou'


class Payment(db.Model):
    __tablename__  = "payment"
    __table_args__ = (
        db.UniqueConstraint("transaction_id",  name="uq_payment_tx"),
        db.UniqueConstraint("external_reference", name="uq_payment_extref"),
    )

    id       = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=True)

    # ✅ fica só esta definição
    order = db.relationship(
        "Order",
        backref=db.backref("payment", uselist=False, cascade="all, delete-orphan"),
        uselist=False,
    )

    method = db.Column(
        PgEnum(PaymentMethod, name="paymentmethod", create_type=False),
        nullable=False,
    )
    status = db.Column(
        PgEnum(PaymentStatus, name="paymentstatus", create_type=False),
        default=PaymentStatus.PENDING,
        index=True,
    )

    transaction_id     = db.Column(db.String(255))
    external_reference = db.Column(db.String(255))
    mercado_pago_id    = db.Column(db.String(64))

    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    user    = db.relationship(
        "User",
        backref=db.backref("payments", cascade="all, delete-orphan"),
    )

    init_point = db.Column(db.String)

    # NOVO: valor congelado do pagamento
    amount = db.Column(db.Numeric(10, 2), nullable=True)  # Adicione este campo


# -------------------------- Planos de Saúde ---------------------------


class PendingWebhook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mp_id = db.Column(db.BigInteger, unique=True)
    attempts = db.Column(db.Integer, default=0)
