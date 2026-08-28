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

    from helpers import membership_for_user
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

    # Vale para as duas âncoras: o passo de pagamento é de quem paga, e quem
    # paga pode ser o responsável pela clínica, sem CRMV.
    membership = membership_for_user(user)
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


def activation_progress(user) -> dict | None:
    """Resumo para a faixa persistente, ou ``None`` quando não há o que mostrar.

    Some sozinha quando todos os passos estão concluídos: um lembrete que não
    sabe terminar vira ruído.
    """
    steps = activation_steps(user)
    if not steps:
        return None

    pending = [step for step in steps if not step['done']]
    if not pending:
        return None

    done = len(steps) - len(pending)
    nxt = pending[0]
    return {
        'done': done,
        'total': len(steps),
        'percent': round(done * 100 / len(steps)),
        'next_label': nxt.get('short') or nxt['label'],
        'next_url': nxt['url'],
        'next_cta': nxt['cta'],
    }


# ---------------------------------------------------------------------------
# Eventos de ativação
#
# Entre ``signup_completed`` e ``trial_converted`` há semanas de trabalho real
# e, até aqui, nenhum registro: quando uma avaliação não convertia, não dava
# para dizer se a pessoa parou antes de cadastrar a clínica, antes do primeiro
# paciente ou na tela de pagamento. São três problemas diferentes.
#
# Cada marco é emitido uma única vez por clínica. A idempotência não usa flag
# nova: o marco só é o primeiro quando a contagem da entidade recém-criada é 1,
# e isso só acontece uma vez na vida da clínica.
# ---------------------------------------------------------------------------


def _track(event_name: str, **properties) -> None:
    """Emite o evento sem jamais derrubar o fluxo que o disparou."""

    try:
        from services.product_analytics import track_event

        track_event(event_name, **properties)
    except Exception:  # noqa: BLE001
        from flask import current_app

        current_app.logger.warning(
            'activation_event_failed', extra={'event_name': event_name}, exc_info=True
        )


def note_clinic_created(clinica, *, user=None) -> None:
    """Primeiro marco depois do cadastro: existe uma operação para ativar."""

    if clinica is None:
        return
    _track(
        'clinic_created',
        stage='clinica',
        city=getattr(clinica, 'cidade', None),
        user_id=getattr(user, 'id', None),
    )


def note_first_patient(clinica_id) -> None:
    """Emite ``first_patient_created`` quando o paciente salvo é o primeiro."""

    if not clinica_id:
        return
    from models import Animal

    total = (
        Animal.query
        .filter(Animal.clinica_id == clinica_id)
        .filter(Animal.removido_em.is_(None))
        .limit(2)
        .count()
    )
    if total == 1:
        _track('first_patient_created', stage='paciente')


def note_first_appointment(clinica_id) -> None:
    """Emite ``first_appointment_created`` quando o agendamento é o primeiro."""

    if not clinica_id:
        return
    from models import Appointment

    total = (
        Appointment.query
        .filter(Appointment.clinica_id == clinica_id)
        .limit(2)
        .count()
    )
    if total == 1:
        _track('first_appointment_created', stage='agendamento')


def note_payment_method_added(membership) -> None:
    """Último marco antes da cobrança: a renovação ficou configurada.

    Sem ``commit``: quem chama está no meio da transação que grava a própria
    autorização, e um commit da telemetria publicaria esse estado antes da
    hora. O evento viaja junto com o commit de quem sabe se a autorização
    valeu — e some junto com o rollback, que é o comportamento correto.
    """

    if membership is None:
        return
    _track('payment_method_added', stage='pagamento', commit=False)
