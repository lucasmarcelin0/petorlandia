"""Aquisição de clínicas no automático.

Três peças, todas sobre a infraestrutura de notificação que já existe:

* ``notify_demo_lead``: o pedido de demonstração chega ao dono na hora (e-mail
  + painel admin, com o link de resposta pronto) e o lead recebe a confirmação.
  Antes ele só era gravado e esperava alguém abrir o Flask-Admin; lead frio é
  lead perdido.
* ``send_activation_nudges``: durante a avaliação, quem ainda não fez os passos
  essenciais (horários, primeiro paciente, primeiro agendamento) recebe um
  e-mail curto com o link do passo pendente. A faixa de ativação só funciona
  para quem volta ao sistema; o e-mail traz de volta quem não voltou.
* ``send_acquisition_digest``: um resumo diário para o dono com o que exige
  ação humana — leads novos, clínicas novas, avaliações travadas e avaliações
  acabando sem renovação —, cada item com o link de contato.

Nada aqui altera dados de clínica: só lê e notifica.
"""

from __future__ import annotations

from datetime import timedelta

from flask import current_app, url_for

from extensions import db
from template_filters import whatsapp_chat_url
from time_utils import coerce_to_brazil_tz, now_in_brazil, utcnow

#: Dias desde o início da avaliação em que lembramos quem não ativou.
#: D+1 com o primeiro passo ainda fresco, D+4 antes de o teste virar
#: esquecimento, D+10 com a oferta de configurar junto. Mais que isso é ruído.
ACTIVATION_NUDGE_OFFSETS = (1, 4, 10)

#: Janela do resumo diário e limite de linhas por seção (o e-mail precisa
#: caber numa leitura de celular).
DIGEST_WINDOW = timedelta(hours=24)
DIGEST_SECTION_LIMIT = 15
#: Avaliação considerada "travada" a partir deste dia sem os passos essenciais.
STALLED_FROM_DAY = 2
#: Avaliações que terminam nestes dias ou menos entram no resumo.
ENDING_SOON_DAYS = 5


def _first_name(user) -> str:
    return ((getattr(user, 'name', '') or '').split(' ')[0]) or 'tudo bem'


def _trial_days() -> int:
    return int(current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30) or 30)


def _support_whatsapp(message: str) -> str | None:
    return whatsapp_chat_url(current_app.config.get('SUPPORT_PHONE'), message)


def _reply_link(contact: str | None, message: str) -> str | None:
    contact = (contact or '').strip()
    if not contact:
        return None
    if '@' in contact:
        return f'mailto:{contact}'
    return whatsapp_chat_url(contact, message)


def _as_aware(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return coerce_to_brazil_tz(value, allow_naive=True)
    return value


# --------------------------------------------------------------- lead de demo


def notify_demo_lead(lead, *, base_url: str) -> None:
    """Avisa o dono do pedido de demonstração e confirma ao lead.

    Melhor esforço: qualquer falha é registrada e nunca derruba o cadastro do
    lead, que já está salvo quando esta função roda.
    """

    from services.notifications import _send_email, notify_admin_action

    # Texto livre do visitante: uma linha só e tamanho limitado, para não
    # virar conteúdo arbitrário no e-mail do dono.
    contact = ' '.join((lead.contact or '').split())[:120]
    city = ' '.join((lead.city or '').split())[:60]
    where = f' em {city}' if city else ''
    reply = _reply_link(
        contact,
        f'Oi! Aqui é da PetOrlândia. Recebemos seu pedido de demonstração{where}. '
        'Qual o melhor dia e horário para mostrarmos o sistema em 15 minutos?',
    )
    lines = [
        f'Contato: {contact}',
        f'Cidade: {city or "não informada"}',
    ]
    if getattr(lead, 'user', None) is not None:
        lines.append(f'Já tem conta: {lead.user.name} ({lead.user.email})')
    lines += [
        '',
        'Responda em até 1 hora: quem responde rápido fecha muito mais.',
    ]
    if reply:
        lines.append(f'Responder agora: {reply}')
    try:
        admin_url = url_for('waitlistlead.index_view', _external=True)
    except Exception:  # noqa: BLE001 - painel admin pode não estar montado
        admin_url = None
    try:
        notify_admin_action(
            title=f'Pedido de demonstração: {contact}{where}',
            body='\n'.join(lines),
            event_type='demo_clinica_lead',
            url=admin_url,
            priority='high',
            entity_type='waitlist_lead',
            entity_id=lead.id,
        )
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception('Falha ao avisar admins do lead de demonstração %s', lead.id)

    if '@' not in contact or ' ' in contact:
        return
    trial_days = _trial_days()
    body = (
        'Olá! Recebemos seu pedido de demonstração da PetOrlândia.\n\n'
        'Vamos falar com você em até 1 dia útil para combinar 15 minutos — por '
        'vídeo ou presencialmente, se você estiver na região de Orlândia.\n\n'
        f'Se quiser adiantar, a avaliação gratuita de {trial_days} dias já está '
        'liberada, sem cartão:\n'
        f'{base_url}/parceiros/clinica\n\n'
        f'Preços e condições: {base_url}/precos\n\n'
        'Se não foi você que fez este pedido, é só ignorar este e-mail.\n\n'
        'Equipe PetOrlândia'
    )
    _send_email([contact], 'Recebemos seu pedido de demonstração — PetOrlândia', body)


# ------------------------------------------------------ régua de ativação


def _pending_required_steps(user, base_url: str) -> list[dict]:
    """Passos essenciais ainda não feitos, com links absolutos.

    Reusa o mesmo cálculo da faixa de ativação (``services.activation``), num
    request de mentira só para o ``url_for`` funcionar fora de uma requisição.
    """

    from services.activation import _compute

    with current_app.test_request_context('/', base_url=base_url):
        steps = _compute(user)
    pending = []
    for step in steps:
        if step['done'] or step.get('optional'):
            continue
        url = step['url']
        if url.startswith('/'):
            url = f'{base_url}{url}'
        pending.append({**step, 'url': url})
    return pending


def _trial_day(membership, today) -> int | None:
    """Dia da avaliação (0 = dia do cadastro), no fuso de Brasília."""
    started = _as_aware(getattr(membership, 'started_at', None))
    if started is None:
        return None
    return (today - coerce_to_brazil_tz(started).date()).days


def _active_trials():
    from models import VeterinarianMembership

    return (
        VeterinarianMembership.query
        .filter(VeterinarianMembership.trial_ends_at.isnot(None))
        .filter(VeterinarianMembership.trial_ends_at >= utcnow())
        .all()
    )


def _nudge_message(user, clinic_name: str, pending: list[dict], day: int, base_url: str):
    nome = _first_name(user)
    passos = '\n'.join(
        f'• {step.get("short") or step["label"]}: {step["url"]}' for step in pending
    )
    ajuda = _support_whatsapp(
        f'Oi! Sou {user.name}, da {clinic_name}. Quero ajuda para configurar a PetOrlândia.'
    )
    contato = f'chame no WhatsApp:\n{ajuda}' if ajuda else 'é só responder este e-mail.'
    if day <= ACTIVATION_NUDGE_OFFSETS[0]:
        assunto = f'Falta pouco para a agenda da {clinic_name} ficar pronta — PetOrlândia'
        abertura = (
            f'Olá {nome}! A {clinic_name} já está cadastrada. Faltam só estes passos '
            'para a PetOrlândia começar a ajudar no dia a dia:'
        )
    elif day <= ACTIVATION_NUDGE_OFFSETS[1]:
        assunto = f'Quer ajuda para configurar a {clinic_name}? — PetOrlândia'
        abertura = (
            f'Olá {nome}! Vimos que a configuração da {clinic_name} ainda não terminou. '
            'Cada passo leva poucos minutos:'
        )
    else:
        assunto = 'Configuramos junto com você, sem custo — PetOrlândia'
        abertura = (
            f'Olá {nome}! Sua avaliação continua ativa, mas a {clinic_name} ainda não '
            'está usando a agenda e o prontuário. O que falta:'
        )
    corpo = (
        f'{abertura}\n\n{passos}\n\n'
        'Prefere que a gente faça junto? Em 30 minutos por vídeo importamos sua '
        'lista de clientes e deixamos a agenda pronta, sem custo — '
        f'{contato}\n\n'
        'Seus dados ficam só com a sua clínica e você pode exportá-los quando quiser.\n\n'
        f'Seu painel de configuração: {base_url}/comecar'
    )
    return assunto, corpo


def send_activation_nudges(*, base_url: str) -> int:
    """Job diário: lembra quem está em avaliação e não fez os passos essenciais."""

    from services.notifications import notify_user

    today = now_in_brazil().date()
    sent = 0
    for membership in _active_trials():
        day = _trial_day(membership, today)
        if day not in ACTIVATION_NUDGE_OFFSETS:
            continue
        user = getattr(getattr(membership, 'veterinario', None), 'user', None)
        clinics = list(getattr(user, 'clinicas', None) or []) if user else []
        if not clinics:
            continue
        try:
            pending = _pending_required_steps(user, base_url)
        except Exception:  # noqa: BLE001 - um usuário com dado ruim não para a régua
            current_app.logger.exception('Falha ao calcular ativação do usuário %s', user.id)
            continue
        if not pending:
            continue
        principal = next((c for c in clinics if c.id == getattr(user, 'clinica_id', None)), clinics[0])
        assunto, corpo = _nudge_message(user, principal.nome, pending, day, base_url)
        notify_user(user, assunto, corpo, kind='activation_nudge')
        sent += 1
    current_app.logger.info('[Ativação] Lembretes de configuração enviados: %s', sent)
    return sent


# ------------------------------------------------------- resumo para o dono


def _user_contact_link(user, clinic=None, message: str = '') -> str:
    phone = getattr(user, 'phone', None) or getattr(clinic, 'telefone', None)
    link = whatsapp_chat_url(phone, message) if phone else None
    if link:
        return link
    email = (getattr(user, 'email', '') or '').strip()
    return f'mailto:{email}' if email else 'sem contato'


def build_acquisition_digest(*, base_url: str) -> dict:
    """Seções do resumo diário. Separado do envio para ser testável."""

    from models import Clinica, VeterinarianMembership, WaitlistLead

    now = utcnow()
    since = now - DIGEST_WINDOW
    today = now_in_brazil().date()

    leads = (
        WaitlistLead.query
        .filter(WaitlistLead.feature == 'demo_clinica')
        .filter(WaitlistLead.created_at >= since)
        .order_by(WaitlistLead.created_at.desc())
        .limit(DIGEST_SECTION_LIMIT)
        .all()
    )
    lead_lines = [
        f'{lead.contact} — {lead.city or "cidade não informada"} — '
        f'{_reply_link(lead.contact, "Oi! Aqui é da PetOrlândia, sobre a demonstração que você pediu.") or ""}'
        for lead in leads
    ]

    new_clinics = (
        Clinica.query
        .filter(Clinica.created_at.isnot(None))
        .filter(Clinica.created_at >= since)
        .order_by(Clinica.created_at.desc())
        .limit(DIGEST_SECTION_LIMIT)
        .all()
    )
    clinic_lines = []
    for clinic in new_clinics:
        owner = getattr(clinic, 'owner', None)
        welcome = (
            f'Oi {_first_name(owner)}! Aqui é da PetOrlândia. Vi que você cadastrou a '
            f'{clinic.nome}. Posso ajudar a deixar a agenda pronta hoje?'
        )
        clinic_lines.append(
            f'{clinic.nome} — {getattr(owner, "name", "sem responsável")} — '
            f'{_user_contact_link(owner, clinic, welcome) if owner else "sem contato"}'
        )

    stalled_lines = []
    ending_lines = []
    active_trials = 0
    for membership in _active_trials():
        active_trials += 1
        user = getattr(getattr(membership, 'veterinario', None), 'user', None)
        if user is None:
            continue
        clinics = list(getattr(user, 'clinicas', None) or [])
        clinic = clinics[0] if clinics else None
        clinic_name = clinic.nome if clinic else 'sem clínica cadastrada'

        trial_end = _as_aware(membership.trial_ends_at)
        days_left = (coerce_to_brazil_tz(trial_end).date() - today).days if trial_end else None
        if (
            days_left is not None
            and days_left <= ENDING_SOON_DAYS
            and not membership.has_payment_method()
            and not membership.has_valid_payment()
            and len(ending_lines) < DIGEST_SECTION_LIMIT
        ):
            message = (
                f'Oi {_first_name(user)}! Aqui é da PetOrlândia. Sua avaliação termina em '
                f'{days_left} dia(s). Posso ajudar a decidir ou tirar alguma dúvida?'
            )
            ending_lines.append(
                f'{user.name} ({clinic_name}) — termina em {days_left} dia(s) — '
                f'{_user_contact_link(user, clinic, message)}'
            )

        day = _trial_day(membership, today)
        if clinic is None or day is None or day < STALLED_FROM_DAY:
            continue
        if len(stalled_lines) >= DIGEST_SECTION_LIMIT:
            continue
        try:
            pending = _pending_required_steps(user, base_url)
        except Exception:  # noqa: BLE001
            current_app.logger.exception('Falha ao calcular ativação do usuário %s', user.id)
            continue
        if not pending:
            continue
        next_step = pending[0].get('short') or pending[0]['label']
        message = (
            f'Oi {_first_name(user)}! Aqui é da PetOrlândia. Vi que a {clinic_name} ainda '
            'não terminou a configuração. Quer que eu ajude agora, em 15 minutos?'
        )
        stalled_lines.append(
            f'{user.name} ({clinic_name}) — dia {day} da avaliação — falta {next_step} — '
            f'{_user_contact_link(user, clinic, message)}'
        )

    paying = (
        VeterinarianMembership.query
        .filter(VeterinarianMembership.paid_until.isnot(None))
        .filter(VeterinarianMembership.paid_until >= now)
        .count()
    )
    return {
        'leads': lead_lines,
        'new_clinics': clinic_lines,
        'stalled': stalled_lines,
        'ending': ending_lines,
        'active_trials': active_trials,
        'paying': paying,
    }


def _digest_body(digest: dict, base_url: str) -> str:
    sections = [
        ('Pedidos de demonstração (24 h) — responda primeiro', digest['leads']),
        ('Clínicas novas (24 h) — dê boas-vindas e ofereça ajuda', digest['new_clinics']),
        ('Avaliações travadas — falta um passo essencial', digest['stalled']),
        ('Avaliações acabando sem renovação configurada', digest['ending']),
    ]
    parts = []
    for title, lines in sections:
        if not lines:
            continue
        parts.append(f'{title}:\n' + '\n'.join(f'• {line}' for line in lines))
    parts.append(
        f'Avaliações ativas: {digest["active_trials"]} · Assinaturas pagas em dia: {digest["paying"]}'
    )
    parts.append(f'Funil completo: {base_url}/painel')
    return '\n\n'.join(parts)


def send_acquisition_digest(*, base_url: str) -> bool:
    """Job diário: resumo para o dono. Só envia quando há algo a fazer."""

    from models import AdminActionNotification
    from services.notifications import notify_admin_action

    digest = build_acquisition_digest(base_url=base_url)
    if not any(digest[key] for key in ('leads', 'new_clinics', 'stalled', 'ending')):
        current_app.logger.info('[Aquisição] Resumo diário: nada pendente.')
        return False

    key = f'acquisition_digest:{now_in_brazil().date().isoformat()}'
    if AdminActionNotification.query.filter_by(idempotency_key=key).first():
        # Reexecução no mesmo dia (reinício do dyno): não repete o e-mail.
        return False

    total = sum(len(digest[k]) for k in ('leads', 'new_clinics', 'stalled', 'ending'))
    notify_admin_action(
        title=f'Aquisição hoje: {total} contato(s) para fazer',
        body=_digest_body(digest, base_url),
        event_type='acquisition_digest',
        priority='high' if digest['leads'] else 'normal',
        idempotency_key=key,
    )
    return True
