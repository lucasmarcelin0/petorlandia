"""Repasse semanal de frete aos entregadores (entregas modo 'plataforma').

O frete das entregas feitas por entregador parceiro fica retido na conta da
plataforma (marketplace_fee). O repasse ao entregador é condicionado à
confirmação de recebimento pelo tutor (``Order.received_at``) e pago em lote,
uma vez por semana, pelo admin — modelo iFood/Uber de ciclo semanal.

Estados de uma entrega concluída (tipo 'plataforma'):
- **aguardando**: tutor ainda não confirmou o recebimento → frete retido;
- **liberado**: recebimento confirmado e ainda não pago → entra no próximo lote;
- **pago**: ``frete_pago_em`` preenchido.
"""
from __future__ import annotations

from decimal import Decimal


def frete_da_entrega(delivery) -> Decimal:
    """Valor de frete a repassar: o congelado na conclusão ou o atual do vendedor."""
    if delivery.frete_valor is not None:
        return Decimal(str(delivery.frete_valor))
    provider = delivery.casa_de_racao or delivery.clinica
    valor = getattr(provider, 'valor_frete', None) if provider else None
    return Decimal(str(valor)) if valor is not None else Decimal('0.00')


def congelar_frete(delivery) -> None:
    """Congela o frete do vendedor na entrega (chamar ao concluir a entrega)."""
    if delivery.frete_valor is None and delivery.tipo_entrega != 'propria':
        delivery.frete_valor = frete_da_entrega(delivery)


def classificar_entrega(delivery) -> str:
    if delivery.frete_pago_em is not None:
        return 'pago'
    order = delivery.order
    if order is not None and order.received_at is not None:
        return 'liberado'
    return 'aguardando'


def resumo_repasses(deliveries) -> list[dict]:
    """Agrupa entregas concluídas por entregador com totais por estado.

    ``deliveries``: entregas tipo 'plataforma' com status 'concluida'.
    Retorna uma lista ordenada por maior valor liberado, um dict por
    entregador: worker, liberadas, aguardando, pagas, total_liberado,
    total_aguardando, total_pago.
    """
    por_entregador: dict[int | None, dict] = {}
    for delivery in deliveries:
        chave = delivery.worker_id
        grupo = por_entregador.setdefault(chave, {
            'worker': delivery.worker,
            'liberadas': [],
            'aguardando': [],
            'pagas': [],
            'total_liberado': Decimal('0.00'),
            'total_aguardando': Decimal('0.00'),
            'total_pago': Decimal('0.00'),
        })
        estado = classificar_entrega(delivery)
        valor = frete_da_entrega(delivery)
        if estado == 'liberado':
            grupo['liberadas'].append(delivery)
            grupo['total_liberado'] += valor
        elif estado == 'aguardando':
            grupo['aguardando'].append(delivery)
            grupo['total_aguardando'] += valor
        else:
            grupo['pagas'].append(delivery)
            grupo['total_pago'] += valor

    return sorted(
        por_entregador.values(),
        key=lambda g: g['total_liberado'],
        reverse=True,
    )
