"""Estoque da loja com histórico de movimentos.

O saldo continua nas colunas inteiras que a loja online já usa
(``product_variant.stock`` e ``product.stock``). Produtos vendidos a granel
(KG, L...) guardam a fração no último movimento: o saldo é a parte inteira
da coluna mais a fração registrada. Assim nada da loja online muda.
"""
from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Iterable, Optional

from extensions import db
from models import EstoqueMovimento, Product, ProductVariant
from models.loja_caixa import UNIDADES_FRACIONADAS


QTD = Decimal("0.0001")

TIPOS_MOVIMENTO = {
    "venda_balcao": "Venda no caixa",
    "cancelamento_venda": "Venda cancelada",
    "venda_online": "Venda online",
    "entrada_nota": "Entrada por nota",
    "ajuste": "Ajuste",
    "inventario": "Inventário",
}


class EstoqueError(ValueError):
    """Dado de estoque inválido; a mensagem vai para a tela."""


def decimal_de(valor, campo: str = "valor") -> Decimal:
    """Aceita 1.234,56 / 1234,56 / 1234.56 e números."""
    if valor is None or valor == "":
        raise EstoqueError(f"Informe {campo}.")
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, (int, float)):
        return Decimal(str(valor))
    texto = str(valor).strip().replace("R$", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = Decimal(texto)
    except InvalidOperation as exc:
        raise EstoqueError(f"{campo.capitalize()} inválido.") from exc
    if not numero.is_finite():
        raise EstoqueError(f"{campo.capitalize()} inválido.")
    return numero


def unidade_de(product: Product) -> str:
    return (product.unidade or "UN").strip().upper()[:6] or "UN"


def fracionado(product: Product) -> bool:
    return unidade_de(product) in UNIDADES_FRACIONADAS


def _ultimo_movimento(product_id: int, variant_id: Optional[int]) -> Optional[EstoqueMovimento]:
    query = EstoqueMovimento.query.filter(EstoqueMovimento.product_id == product_id)
    if variant_id is None:
        query = query.filter(EstoqueMovimento.variant_id.is_(None))
    else:
        query = query.filter(EstoqueMovimento.variant_id == variant_id)
    return query.order_by(EstoqueMovimento.id.desc()).first()


def saldo(product: Product, variant: Optional[ProductVariant] = None) -> Decimal:
    """Saldo atual: coluna inteira (+ fração do granel)."""
    base = Decimal(int((variant.stock if variant is not None else product.stock) or 0))
    if not fracionado(product):
        return base
    ultimo = _ultimo_movimento(product.id, variant.id if variant is not None else None)
    if ultimo is None or ultimo.saldo_apos is None:
        return base
    anterior = Decimal(ultimo.saldo_apos)
    fracao = anterior - anterior.to_integral_value(rounding=ROUND_FLOOR)
    return base + fracao


def travar_saldos(product_ids: Iterable[int], variant_ids: Iterable[int] = ()) -> None:
    """Bloqueia os saldos (SELECT ... FOR UPDATE) até o commit e relê os valores.

    ``movimentar`` calcula o saldo novo em Python; sem o bloqueio, duas
    operações simultâneas no mesmo produto sobrescreveriam uma à outra.
    Sempre na mesma ordem (por id), como a venda do caixa, para não travar.
    """
    ids = sorted({int(i) for i in product_ids if i})
    if ids:
        Product.query.filter(Product.id.in_(ids)).order_by(Product.id).with_for_update().populate_existing().all()
    ids_variantes = sorted({int(i) for i in variant_ids if i})
    if ids_variantes:
        (
            ProductVariant.query.filter(ProductVariant.id.in_(ids_variantes))
            .order_by(ProductVariant.id)
            .with_for_update()
            .populate_existing()
            .all()
        )


def movimentar(
    *,
    casa_de_racao_id: int,
    product: Product,
    variant: Optional[ProductVariant],
    quantidade: Decimal,
    tipo: str,
    referencia_tipo: str | None = None,
    referencia_id: int | None = None,
    usuario_id: int | None = None,
    custo_unitario: Decimal | None = None,
    observacao: str | None = None,
) -> EstoqueMovimento:
    """Soma ``quantidade`` (negativa = saída) ao saldo e registra o movimento.

    Como na loja online, o saldo não fica negativo: vender sem estoque
    registrado zera o saldo e o movimento mostra o que foi pedido.
    """
    quantidade = Decimal(quantidade).quantize(QTD)
    if not fracionado(product) and quantidade != quantidade.to_integral_value():
        raise EstoqueError(f"\"{product.name}\" é vendido por unidade inteira.")
    atual = saldo(product, variant)
    novo = max(Decimal("0"), atual + quantidade)
    inteiro = int(novo.to_integral_value(rounding=ROUND_FLOOR))
    if variant is not None:
        diferenca = inteiro - int(variant.stock or 0)
        variant.stock = inteiro
        product.stock = max(0, int(product.stock or 0) + diferenca)
    else:
        product.stock = inteiro
    movimento = EstoqueMovimento(
        casa_de_racao_id=casa_de_racao_id,
        product_id=product.id,
        variant_id=variant.id if variant is not None else None,
        tipo=tipo,
        quantidade=quantidade,
        saldo_apos=novo,
        custo_unitario=custo_unitario,
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        observacao=(observacao or "")[:255] or None,
        usuario_id=usuario_id,
    )
    db.session.add(movimento)
    return movimento


def ajustar_para(
    *,
    casa_de_racao_id: int,
    product: Product,
    variant: Optional[ProductVariant],
    novo_saldo: Decimal,
    tipo: str = "ajuste",
    usuario_id: int | None = None,
    observacao: str | None = None,
) -> Optional[EstoqueMovimento]:
    """Leva o saldo a ``novo_saldo`` (inventário/ajuste). Sem diferença, nada grava."""
    novo_saldo = Decimal(novo_saldo).quantize(QTD)
    if novo_saldo < 0:
        raise EstoqueError("O saldo não pode ser negativo.")
    diferenca = novo_saldo - saldo(product, variant)
    if diferenca == 0:
        return None
    return movimentar(
        casa_de_racao_id=casa_de_racao_id,
        product=product,
        variant=variant,
        quantidade=diferenca,
        tipo=tipo,
        usuario_id=usuario_id,
        observacao=observacao,
    )


def formatar_quantidade(valor, unidade: str = "UN") -> str:
    numero = Decimal(valor or 0)
    if (unidade or "UN").upper() in UNIDADES_FRACIONADAS:
        texto = f"{numero.quantize(Decimal('0.001')):f}".rstrip("0").rstrip(".")
    else:
        texto = f"{numero.to_integral_value():f}"
    return texto.replace(".", ",")
