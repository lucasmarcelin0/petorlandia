"""Avisa tutor e profissional assim que um compromisso é agendado.

Por que gancho de sessão e não uma chamada em cada rota: um compromisso nasce
em pelo menos sete lugares diferentes (``blueprints/agendamentos``,
``blueprints/site``, ``services/appointments``, ``app.py``, além do fluxo de
retorno dentro da consulta). Espalhar a chamada significa esquecer o próximo
ponto de criação — o gancho pega inclusive os que ainda não existem.

A linha em ``Notification`` (o aviso dentro do app) é gravada em
``before_flush``, ou seja, na MESMA transação do compromisso: ou os dois
existem ou nenhum existe. E-mail e push saem só em ``after_commit``, porque
efeito externo não pode vazar de uma transação que ainda pode dar rollback.
"""

from __future__ import annotations

from flask import current_app
from sqlalchemy import event

from time_utils import BR_TZ

#: Payloads prontos aguardando o commit para virar e-mail/push.
_PENDING_KEY = 'appointment_notifications_pending'
#: Objetos já processados nesta sessão, para o caso de vários flushes.
_SEEN_KEY = 'appointment_notifications_seen'

APP_TITLE = 'PetOrlândia 🐾'


def _format_datetime(value):
    if value is None:
        return 'data a confirmar'
    try:
        if value.tzinfo is not None:
            value = value.astimezone(BR_TZ)
        return value.strftime('%d/%m/%Y às %H:%M')
    except (AttributeError, ValueError):
        return str(value)


def _format_date(value):
    if value is None:
        return 'data a confirmar'
    try:
        return value.strftime('%d/%m/%Y')
    except (AttributeError, ValueError):
        return str(value)


def _resolve(loaded, model, pk):
    """Objeto já ligado, ou busca pela chave estrangeira.

    Em ``before_flush`` o compromisso ainda é *pending*: o SQLAlchemy não
    dispara lazy load de relacionamento para instância sem identidade, então
    ``appt.animal`` volta ``None`` mesmo com ``animal_id`` preenchido. Sem
    resolver pela FK a mensagem sairia como "seu pet" e o tutor sequer seria
    encontrado — o aviso não chegaria a ninguém.
    """

    if loaded is not None:
        return loaded
    if not pk:
        return None
    from extensions import db

    return db.session.get(model, pk)


def _animal_of(obj):
    from models import Animal

    return _resolve(
        obj.__dict__.get('animal'), Animal, getattr(obj, 'animal_id', None)
    )


def _vet_of(obj, attr, fk_attr):
    from models import Veterinario

    return _resolve(
        obj.__dict__.get(attr), Veterinario, getattr(obj, fk_attr, None)
    )


def _animal_name(animal):
    return getattr(animal, 'name', None) or 'seu pet'


def _vet_user_id(veterinario):
    return getattr(veterinario, 'user_id', None)


def _vet_name(veterinario):
    return getattr(getattr(veterinario, 'user', None), 'name', None)


def _describe_appointment(appt):
    """(assunto, texto, id do profissional, id de quem criou) de um ``Appointment``."""

    from services.appointment_status import kind_label

    label = kind_label(getattr(appt, 'kind', None) or 'consulta')
    animal_obj = _animal_of(appt)
    veterinario = _vet_of(appt, 'veterinario', 'veterinario_id')
    animal = _animal_name(animal_obj)
    quando = _format_datetime(getattr(appt, 'scheduled_at', None))
    vet_name = _vet_name(veterinario)

    texto = f'{label} de {animal} agendada para {quando}'
    if vet_name:
        texto += f' com {vet_name}'
    texto += '.'

    return (
        f'{label} agendada - PetOrlandia',
        texto,
        _vet_user_id(veterinario),
        getattr(appt, 'created_by', None),
        getattr(appt, 'tutor_id', None) or getattr(animal_obj, 'user_id', None),
        'appointment',
    )


def _describe_exam_appointment(exam):
    animal_obj = _animal_of(exam)
    specialist = _vet_of(exam, 'specialist', 'specialist_id')
    animal = _animal_name(animal_obj)
    quando = _format_datetime(getattr(exam, 'scheduled_at', None))
    nome = getattr(exam, 'exam_name', None)
    especialista = _vet_name(specialist)

    alvo = f"Exame '{nome}'" if nome else 'Exame'
    texto = f'{alvo} de {animal} agendado para {quando}'
    if especialista:
        texto += f' com {especialista}'
    texto += '.'

    return (
        'Exame agendado - PetOrlandia',
        texto,
        _vet_user_id(specialist),
        getattr(exam, 'requester_id', None),
        getattr(animal_obj, 'user_id', None),
        'exam',
    )


def _describe_vacina(vacina):
    animal_obj = _animal_of(vacina)
    animal = _animal_name(animal_obj)
    quando = _format_date(getattr(vacina, 'aplicada_em', None))
    nome = getattr(vacina, 'nome', None)

    alvo = f"Vacina '{nome}'" if nome else 'Vacina'
    texto = f'{alvo} de {animal} agendada para {quando}.'

    return (
        'Vacina agendada - PetOrlandia',
        texto,
        None,
        getattr(vacina, 'created_by', None),
        getattr(animal_obj, 'user_id', None),
        'vaccine',
    )


def _is_future_vacina(vacina):
    """Só é agendamento a vacina ainda não aplicada e com data à frente.

    Uma vacina já aplicada é registro de histórico: avisar "foi agendada" ao
    salvar o histórico seria mentira, e todo import de carteirinha viraria
    enxurrada de notificação.
    """

    from datetime import date

    if getattr(vacina, 'aplicada', False):
        return False
    aplicada_em = getattr(vacina, 'aplicada_em', None)
    if aplicada_em is None:
        return False
    try:
        return aplicada_em >= date.today()
    except TypeError:
        return False


def _describe(obj):
    """Descreve o objeto agendado, ou ``None`` se ele não for um agendamento."""

    from models import Appointment, ExamAppointment, Vacina

    if isinstance(obj, Appointment):
        return _describe_appointment(obj)
    if isinstance(obj, ExamAppointment):
        return _describe_exam_appointment(obj)
    if isinstance(obj, Vacina) and _is_future_vacina(obj):
        return _describe_vacina(obj)
    return None


def _collect_recipients(professional_user_id, creator_id, tutor_id):
    """Tutor sempre; profissional só quando não foi ele quem agendou.

    Ninguém precisa ser avisado da própria ação — é o que separa notificação
    útil de ruído.
    """

    recipients = []
    for user_id in (tutor_id, professional_user_id):
        if not user_id:
            continue
        if creator_id and int(user_id) == int(creator_id):
            continue
        if user_id in recipients:
            continue
        recipients.append(user_id)
    return recipients


def _handle_before_flush(session, flush_context, instances):
    from models import Notification

    seen = session.info.setdefault(_SEEN_KEY, set())
    pending = session.info.setdefault(_PENDING_KEY, [])

    # ``session.new`` é uma coleção viva: materializa antes de inserir nela.
    novos = list(session.new)

    for obj in novos:
        marker = id(obj)
        if marker in seen:
            continue

        try:
            # Carregar ``animal``/``veterinario`` aqui dispararia autoflush
            # reentrante — no_autoflush é o que mantém o gancho inofensivo.
            with session.no_autoflush:
                described = _describe(obj)
        except Exception:  # noqa: BLE001 — aviso nunca derruba o agendamento
            current_app.logger.exception(
                'Falha ao descrever agendamento para notificacao'
            )
            seen.add(marker)
            continue

        if described is None:
            continue

        seen.add(marker)
        subject, texto, professional_user_id, creator_id, tutor_id, kind = described
        recipients = _collect_recipients(professional_user_id, creator_id, tutor_id)
        if not recipients:
            continue

        for user_id in recipients:
            session.add(
                Notification(
                    user_id=user_id,
                    message=texto,
                    channel='app',
                    kind=kind,
                )
            )

        pending.append(
            {
                'recipients': recipients,
                'subject': subject,
                'message': texto,
                'kind': kind,
            }
        )


def _handle_after_commit(session):
    pending = session.info.pop(_PENDING_KEY, None)
    session.info.pop(_SEEN_KEY, None)
    if not pending:
        return

    for payload in pending:
        try:
            _deliver(payload)
        except Exception:  # noqa: BLE001 — entrega é best-effort
            current_app.logger.exception(
                'Falha ao entregar notificacao de agendamento (%s)',
                payload.get('kind'),
            )


def _handle_rollback(session, previous_transaction=None):
    session.info.pop(_PENDING_KEY, None)
    session.info.pop(_SEEN_KEY, None)


def _deliver(payload):
    from models import User
    from services.notifications import _send_email
    from services.push import push_to_user

    message = payload['message']
    for user_id in payload['recipients']:
        user = User.query.get(user_id)
        if user is None:
            continue

        email = (getattr(user, 'email', '') or '').strip()
        # Convites internos usam e-mail sintético; mandar para lá só gera bounce.
        if email and not email.endswith('@convite.petorlandia.local'):
            _send_email([email], payload['subject'], message)

        push_to_user(user_id, APP_TITLE, message, url='/appointments', tag='agendamento')


def register_appointment_notifications(db):
    """Liga os ganchos na sessão do SQLAlchemy. Idempotente."""

    session = db.session
    if getattr(register_appointment_notifications, '_registered', False):
        return
    event.listen(session, 'before_flush', _handle_before_flush)
    event.listen(session, 'after_commit', _handle_after_commit)
    event.listen(session, 'after_soft_rollback', _handle_rollback)
    register_appointment_notifications._registered = True


__all__ = ['register_appointment_notifications']
