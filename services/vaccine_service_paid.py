"""Serviço de vacinas pagas: catálogo, pedidos, pagamento e ciclo de vida.

Fluxo: pedido criado (pendente_pagamento) → webhook MP aprova (pago) →
admin atribui veterinário (atribuido) → agenda (agendado) → aplica
(concluido, gera registro Vacina no animal). Cancelamento/reembolso e
reagendamento em um clique, com histórico completo em VaccineServiceEvent.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from extensions import db
from time_utils import utcnow


EVENT_LABELS = {
    'criado': 'Pedido criado',
    'pagamento_iniciado': 'Pagamento iniciado',
    'pago': 'Pagamento aprovado',
    'atribuido': 'Veterinário designado',
    'agendado': 'Visita agendada',
    'reagendado': 'Visita reagendada',
    'concluido': 'Vacina aplicada',
    'cancelado': 'Pedido cancelado',
    'reembolso_solicitado': 'Reembolso solicitado',
    'reembolsado': 'Reembolso concluído',
}


def log_event(req, event: str, note: str = '', actor_user_id: int | None = None) -> None:
    from models import VaccineServiceEvent

    db.session.add(VaccineServiceEvent(
        request_id=req.id,
        event=event,
        note=note or None,
        actor_user_id=actor_user_id,
    ))


def list_active_items():
    from models import VaccineServiceItem

    return (
        VaccineServiceItem.query
        .filter_by(ativo=True)
        .order_by(VaccineServiceItem.position, VaccineServiceItem.nome)
        .all()
    )


def create_vaccine_request(
    *,
    user,
    animal,
    items=None,
    item=None,
    payload: dict[str, Any],
    criar_preferencia: Callable[[list[dict], str, str], dict],
    back_url_builder: Callable[[str], str],
) -> tuple[Any, str]:
    """Cria o pedido + Payment + preferência MP. Retorna (request, payment_url)."""
    from models import (
        Payment,
        PaymentMethod,
        VaccineServiceRequest,
        VaccineServiceRequestItem,
    )

    selected_items = list(items or ([item] if item is not None else []))
    if not selected_items:
        raise ValueError('Escolha pelo menos uma vacina.')

    provider_ids = {selected.provider_vet_id for selected in selected_items}
    if len(provider_ids) > 1:
        raise ValueError('As vacinas selecionadas precisam ser aplicadas pelo mesmo profissional.')

    total = sum((Decimal(str(selected.preco)) for selected in selected_items), Decimal('0.00'))
    payout_total = sum(
        (
            Decimal(str(selected.valor_repasse))
            for selected in selected_items
            if selected.valor_repasse is not None
        ),
        Decimal('0.00'),
    )
    first_item = selected_items[0]
    item_names = ', '.join(selected.nome for selected in selected_items)
    manufacturers = ', '.join(dict.fromkeys(
        selected.fabricante for selected in selected_items if selected.fabricante
    ))

    req = VaccineServiceRequest(
        user_id=user.id,
        animal_id=animal.id,
        item_id=first_item.id,
        item_nome=item_names,
        valor=total,
        fabricante=manufacturers or None,
        valor_repasse=payout_total,
        address_street=(payload.get('address_street') or '').strip() or None,
        address_number=(payload.get('address_number') or '').strip() or None,
        address_complement=(payload.get('address_complement') or '').strip() or None,
        address_neighborhood=(payload.get('address_neighborhood') or '').strip() or None,
        phone=(payload.get('phone') or '').strip() or None,
        preferred_date=payload.get('preferred_date'),
        preferred_shift=(payload.get('preferred_shift') or '').strip() or None,
        note=(payload.get('note') or '').strip() or None,
        status='pendente_pagamento',
        public_token=secrets.token_urlsafe(32),
        assigned_vet_id=first_item.provider_vet_id,
    )
    db.session.add(req)
    db.session.flush()  # garante req.id para a external_reference

    for selected in selected_items:
        db.session.add(VaccineServiceRequestItem(
            request_id=req.id,
            item_id=selected.id,
            nome=selected.nome,
            fabricante=selected.fabricante,
            valor=selected.preco,
            valor_repasse=selected.valor_repasse,
        ))

    extref = f'vacserv-{req.id}'
    items_payload = [
        {
            'id': f'vacserv-item-{selected.id}',
            'title': f'{selected.nome} — {animal.name or "Pet"}',
            'quantity': 1,
            'unit_price': float(selected.preco),
        }
        for selected in selected_items
    ]
    preference = criar_preferencia(items_payload, extref, back_url_builder(req.public_token))

    payment = Payment(
        user_id=user.id,
        method=PaymentMethod.PIX,
        external_reference=extref,
        init_point=preference['payment_url'],
        amount=total,
    )
    db.session.add(payment)
    db.session.flush()
    req.payment_id = payment.id

    log_event(req, 'criado', f'{item_names} para {animal.name or "pet"}', user.id)
    log_event(req, 'pagamento_iniciado', actor_user_id=user.id)
    db.session.commit()
    return req, preference['payment_url']


def mark_request_paid(req) -> bool:
    """Chamado pelo webhook quando o pagamento é aprovado. Idempotente."""
    if req.status != 'pendente_pagamento':
        return False
    req.status = 'atribuido' if req.assigned_vet_id else 'pago'
    log_event(req, 'pago')
    if req.assigned_vet_id and req.assigned_vet:
        vet_name = getattr(getattr(req.assigned_vet, 'user', None), 'name', None)
        log_event(req, 'atribuido', vet_name or f'Vet #{req.assigned_vet_id}')
    return True


def assign_vet(req, vet, actor_user_id: int) -> None:
    if req.status not in ('pago', 'atribuido'):
        raise ValueError('Pedido precisa estar pago para designar veterinário.')
    req.assigned_vet_id = vet.id
    req.status = 'atribuido'
    vet_name = getattr(getattr(vet, 'user', None), 'name', None) or f'Vet #{vet.id}'
    log_event(req, 'atribuido', vet_name, actor_user_id)


def schedule_request(req, scheduled_date: date, scheduled_shift: str, actor_user_id: int) -> None:
    if req.status not in ('atribuido', 'agendado'):
        raise ValueError('Designe um veterinário antes de agendar.')
    rescheduling = req.status == 'agendado'
    req.scheduled_date = scheduled_date
    req.scheduled_shift = scheduled_shift or None
    req.status = 'agendado'
    note = scheduled_date.strftime('%d/%m/%Y') + (f' · {scheduled_shift}' if scheduled_shift else '')
    log_event(req, 'reagendado' if rescheduling else 'agendado', note, actor_user_id)


def request_reschedule(req, preferred_date: date | None, note: str, actor_user_id: int) -> None:
    """Tutor pede outra data: volta para 'atribuido' e o admin reagenda."""
    if req.status not in ('agendado', 'atribuido'):
        raise ValueError('Este pedido não pode ser reagendado agora.')
    req.preferred_date = preferred_date
    req.scheduled_date = None
    req.scheduled_shift = None
    if req.status == 'agendado':
        req.status = 'atribuido'
    detail = preferred_date.strftime('%d/%m/%Y') if preferred_date else 'sem data preferida'
    log_event(req, 'reagendado', f'Tutor pediu nova data ({detail}). {note}'.strip(), actor_user_id)


def complete_request(req, actor_user_id: int, lote: str = '') -> None:
    """Marca aplicada e cria os registros de vacina no prontuário do animal."""
    from models import Vacina

    if req.status not in ('agendado', 'atribuido'):
        raise ValueError('Pedido precisa estar agendado para concluir.')

    request_items = list(req.request_items)
    vaccine_names = [entry.nome for entry in request_items] or [req.item_nome]
    first_vaccine = None
    for index, vaccine_name in enumerate(vaccine_names):
        vacina = Vacina(
            animal_id=req.animal_id,
            nome=vaccine_name,
            tipo='Particular',
            aplicada=True,
            aplicada_em=date.today(),
            lote=lote or None,
            aplicada_por=(
                req.assigned_vet.user_id
                if req.assigned_vet and getattr(req.assigned_vet, 'user_id', None)
                else None
            ),
            created_by=actor_user_id,
        )
        db.session.add(vacina)
        db.session.flush()
        if index < len(request_items):
            request_items[index].vacina_id = vacina.id
        if first_vaccine is None:
            first_vaccine = vacina
    req.vacina_id = first_vaccine.id
    req.vaccinated_at = utcnow()
    req.status = 'concluido'
    log_event(req, 'concluido', f'Lote {lote}' if lote else '', actor_user_id)


def cancel_request(
    req,
    *,
    reason: str,
    actor_user_id: int,
    refund_payment: Callable[[Any], bool] | None = None,
) -> str:
    """Cancela o pedido. Se já pago, tenta reembolso automático via MP.

    Retorna: 'cancelado' | 'reembolsado' | 'reembolso_pendente'
    """
    if req.status in ('concluido', 'cancelado', 'reembolsado'):
        raise ValueError('Este pedido não pode mais ser cancelado.')

    was_paid = req.status in ('pago', 'atribuido', 'agendado')
    req.cancel_reason = (reason or '').strip()[:255] or None
    log_event(req, 'cancelado', req.cancel_reason or '', actor_user_id)

    if not was_paid:
        req.status = 'cancelado'
        return 'cancelado'

    req.status = 'cancelado'
    req.refund_status = 'solicitado'
    log_event(req, 'reembolso_solicitado', actor_user_id=actor_user_id)

    if refund_payment and req.payment:
        try:
            if refund_payment(req.payment):
                req.status = 'reembolsado'
                req.refund_status = 'concluido'
                log_event(req, 'reembolsado')
                return 'reembolsado'
        except Exception:
            req.refund_status = 'falhou'
    return 'reembolso_pendente'


def timeline_for(req) -> list[dict[str, Any]]:
    """Eventos formatados para a linha do tempo da página pública."""
    out = []
    for ev in req.events:
        out.append({
            'event': ev.event,
            'label': EVENT_LABELS.get(ev.event, ev.event),
            'note': ev.note or '',
            'at': ev.created_at,
        })
    return out
