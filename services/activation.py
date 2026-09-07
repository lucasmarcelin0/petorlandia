"""Passos de ativação de uma clínica nova, calculados a partir do uso real.

A lista existia só na tela de boas-vindas — a página que a pessoa vê uma vez,
logo depois do cadastro, e tipicamente nunca mais. Quem parava no passo 2 não
tinha nada puxando de volta para o passo 3 durante os dias de avaliação.

Este módulo isola o cálculo para que a mesma verdade alimente as duas
superfícies: a tela de boas-vindas e a faixa fina que acompanha o app enquanto
a ativação não termina.
"""

from __future__ import annotations

from flask import url_for

_PANEL_CACHE_KEY = '_activation_steps_cache'


def activation_steps(user) -> list[dict]:
    """Passos de ativação da clínica deste usuário.

    Devolve lista vazia para quem ainda não tem clínica — a ativação só faz
    sentido depois que existe uma operação para ativar.
    """
    from flask import g

    cached = getattr(g, _PANEL_CACHE_KEY, None)
    if cached is not None:
        return cached

    steps = _compute(user)
    setattr(g, _PANEL_CACHE_KEY, steps)
    return steps


def _compute(user) -> list[dict]:
    if not getattr(user, 'is_authenticated', False):
        return []

    clinicas = getattr(user, 'clinicas', None)
    if not clinicas:
        return []

    from helpers import ensure_veterinarian_membership, has_veterinarian_profile
    from models import Animal, Appointment

    clinic_ids = [clinic.id for clinic in clinicas]

    has_patient = bool(
        Animal.query
        .filter(Animal.clinica_id.in_(clinic_ids))
        .filter(Animal.removido_em.is_(None))
        .first()
    )
    has_appointment = bool(
        Appointment.query.filter(Appointment.clinica_id.in_(clinic_ids)).first()
    )

    membership = None
    if has_veterinarian_profile(user):
        membership = ensure_veterinarian_membership(user.veterinario)
    has_payment = bool(membership and membership.has_payment_method())

    return [
        {
            'label': 'Clínica cadastrada',
            'done': True,
            'url': url_for('minha_clinica'),
            'cta': 'Abrir clínica',
        },
        {
            'label': 'Primeiro paciente cadastrado',
            'done': has_patient,
            'url': url_for('novo_animal'),
            'cta': 'Cadastrar paciente',
            'short': 'cadastrar o primeiro paciente',
        },
        {
            'label': 'Primeiro agendamento criado',
            'done': has_appointment,
            'url': url_for('appointments'),
            'cta': 'Criar agendamento',
            'short': 'criar o primeiro agendamento',
        },
        {
            'label': 'Renovação configurada',
            'done': has_payment,
            'url': url_for('veterinarian_membership'),
            'cta': 'Ver assinatura',
            'short': 'configurar a renovação',
            'optional': True,
        },
    ]


def membership_attention(membership) -> str | None:
    """Require attention only for expired access or imminent manual renewal."""
    if not membership:
        return None
    from datetime import timedelta
    from time_utils import utcnow

    now = utcnow()
    dates = [membership._as_timezone_aware(value) for value in
             (membership.trial_ends_at, membership.paid_until) if value is not None]
    if not dates:
        return None
    access_until = max(dates)
    if access_until < now:
        return ('Período pago encerrado. Revise sua assinatura.' if membership.paid_until
                else 'Avaliação encerrada. Ative sua assinatura para continuar.')
    if access_until <= now + timedelta(days=3) and not membership.has_payment_method():
        return 'Seu acesso vence em até 3 dias. Configure a renovação.'
    return None


def activation_progress(user, *, include_dismissed=False) -> dict | None:
    """Resumo para a faixa persistente, ou ``None`` quando não há o que mostrar.

    Some sozinha quando todos os passos estão concluídos: um lembrete que não
    sabe terminar vira ruído.
    """
    if not getattr(user, 'is_authenticated', False):
        return None
    membership = getattr(getattr(user, 'veterinario', None), 'membership', None)
    urgent = membership_attention(membership)
    if urgent:
        return dict(urgent=True, next_label=urgent, next_url=url_for('veterinarian_membership'),
                    next_cta='Ver assinatura')
    steps = activation_steps(user)
    if not steps:
        return None

    pending = [step for step in steps if not step['done']]
    if not pending:
        return None

    done = len(steps) - len(pending)
    nxt = pending[0]
    progress = {
        'urgent': False,
        'done': done,
        'total': len(steps),
        'percent': round(done * 100 / len(steps)),
        'next_label': nxt.get('short') or nxt['label'],
        'next_url': nxt['url'],
        'next_cta': nxt['cta'],
    }
    from services.home_alerts import prepare_alerts
    reminder = prepare_alerts(user.id, [dict(url=url_for('veterinarian_membership'),
        label='Configuração inicial da clínica', detail='activation-bar-v1')])[0]
    if reminder['dismissed'] and not include_dismissed:
        return None
    progress['dismiss_token'] = reminder['dismiss_token']
    return progress
