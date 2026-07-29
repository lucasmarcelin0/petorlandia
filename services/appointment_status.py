"""Fonte única de verdade para os status de agendamento.

Antes desta módulo cada template repetia sua própria cadeia de ternários para
traduzir ``Appointment.status`` em rótulo/cor/ícone, o que fazia o mesmo status
aparecer com nomes e cores diferentes no calendário, na lista e nos cards.
Todo consumidor (Python, Jinja e JavaScript) passa a ler daqui.
"""

from __future__ import annotations

# Ordem de progressão natural do atendimento. Usada para ordenar filtros e
# para decidir o que ainda é "aberto" (precisa de ação do profissional).
APPOINTMENT_STATUS_META = {
    'scheduled': {
        'label': 'A confirmar',
        'short': 'A confirmar',
        'icon': 'fa-solid fa-hourglass-half',
        'tone': 'warning',
        'order': 1,
        'open': True,
        'description': 'Aguardando confirmação do profissional.',
    },
    'accepted': {
        'label': 'Confirmada',
        'short': 'Confirmada',
        'icon': 'fa-solid fa-circle-check',
        'tone': 'info',
        'order': 2,
        'open': True,
        'description': 'Confirmada e aguardando o atendimento.',
    },
    'in_progress': {
        'label': 'Em atendimento',
        'short': 'Em atendimento',
        'icon': 'fa-solid fa-stethoscope',
        'tone': 'primary',
        'order': 3,
        'open': True,
        'description': 'Consulta iniciada e ainda não finalizada.',
    },
    'completed': {
        'label': 'Finalizada',
        'short': 'Finalizada',
        'icon': 'fa-solid fa-clipboard-check',
        'tone': 'success',
        'order': 4,
        'open': False,
        'description': 'Atendimento concluído.',
    },
    'no_show': {
        'label': 'Não compareceu',
        'short': 'Faltou',
        'icon': 'fa-solid fa-user-slash',
        'tone': 'danger',
        'order': 5,
        'open': False,
        'description': 'O paciente não compareceu no horário marcado.',
    },
    'canceled': {
        'label': 'Cancelada',
        'short': 'Cancelada',
        'icon': 'fa-solid fa-ban',
        'tone': 'muted',
        'order': 6,
        'open': False,
        'description': 'Agendamento cancelado.',
    },
}

DEFAULT_STATUS_META = {
    'label': 'Status desconhecido',
    'short': 'Indefinido',
    'icon': 'fa-solid fa-circle-question',
    'tone': 'muted',
    'order': 99,
    'open': False,
    'description': '',
}

# Rótulos simples mantidos para quem só precisa do texto (filtros, exports).
APPOINTMENT_STATUS_LABELS = {
    key: meta['label'] for key, meta in APPOINTMENT_STATUS_META.items()
}

# Status que ainda pedem alguma ação — usados para contadores e badges.
OPEN_APPOINTMENT_STATUSES = tuple(
    key for key, meta in APPOINTMENT_STATUS_META.items() if meta['open']
)

# Status que impedem reabrir/reaproveitar o agendamento.
CLOSED_APPOINTMENT_STATUSES = tuple(
    key for key, meta in APPOINTMENT_STATUS_META.items() if not meta['open']
)

# Status aceitos pelo endpoint de atualização manual.
SETTABLE_APPOINTMENT_STATUSES = frozenset(APPOINTMENT_STATUS_META)


def status_meta(status):
    """Retorna os metadados de ``status`` com fallback seguro."""

    meta = APPOINTMENT_STATUS_META.get(status)
    if meta:
        return dict(meta, key=status)
    label = (status or '').replace('_', ' ').strip().capitalize()
    return dict(
        DEFAULT_STATUS_META,
        key=status,
        label=label or DEFAULT_STATUS_META['label'],
        short=label or DEFAULT_STATUS_META['short'],
    )


def status_label(status):
    """Rótulo humano para ``status``."""

    return status_meta(status)['label']


def is_open_status(status):
    """``True`` quando o agendamento ainda aguarda alguma ação."""

    return bool(status_meta(status).get('open'))


# ---------------------------------------------------------------------------
# Tipos de atendimento (kind)
# ---------------------------------------------------------------------------

APPOINTMENT_KIND_META = {
    'consulta': {'label': 'Consulta', 'icon': 'fa-solid fa-stethoscope', 'tone': 'primary'},
    'retorno': {'label': 'Retorno', 'icon': 'fa-solid fa-rotate-left', 'tone': 'warning'},
    'exame': {'label': 'Exame', 'icon': 'fa-solid fa-vial', 'tone': 'purple'},
    'banho_tosa': {'label': 'Banho e Tosa', 'icon': 'fa-solid fa-shower', 'tone': 'info'},
    'vacina': {'label': 'Vacina', 'icon': 'fa-solid fa-syringe', 'tone': 'success'},
    'general': {'label': 'Consulta', 'icon': 'fa-solid fa-stethoscope', 'tone': 'primary'},
}

DEFAULT_KIND_META = {
    'label': 'Atendimento',
    'icon': 'fa-solid fa-calendar-day',
    'tone': 'muted',
}

APPOINTMENT_KIND_LABELS = {
    key: meta['label'] for key, meta in APPOINTMENT_KIND_META.items()
}
# ``general`` é um sinônimo interno de consulta, mas o rótulo antigo é mantido
# nos filtros administrativos para não quebrar relatórios já salvos.
APPOINTMENT_KIND_LABELS['general'] = 'Geral'


def kind_meta(kind):
    """Retorna os metadados do tipo de atendimento com fallback seguro."""

    meta = APPOINTMENT_KIND_META.get(kind)
    if meta:
        return dict(meta, key=kind)
    label = (kind or '').replace('_', ' ').strip().title()
    return dict(
        DEFAULT_KIND_META,
        key=kind,
        label=label or DEFAULT_KIND_META['label'],
    )


def kind_label(kind):
    """Rótulo humano para o tipo de atendimento."""

    return kind_meta(kind)['label']


def normalize_kind(kind, *, has_consulta=False):
    """Normaliza ``kind`` para os valores exibidos na agenda.

    ``general`` é o default histórico da coluna e sempre significou consulta;
    agendamentos sem ``kind`` mas ligados a uma consulta anterior são retornos.
    """

    if not kind:
        return 'retorno' if has_consulta else 'consulta'
    if kind == 'general':
        return 'consulta'
    return kind
