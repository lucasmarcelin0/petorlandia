"""Context processors globais do Jinja e cache de contexto por usuário.

Extraído de app.py durante a modularização. Registrar com:

    from context_processors import register_context_processors
    register_context_processors(app)

O cache aqui é in-process com TTL curto: evita repetir as queries de badge
(navbar) a cada request. As funções de invalidação são importadas pelas views
que alteram os dados exibidos nos badges.
"""
from __future__ import annotations

import time as _time_module
from types import SimpleNamespace

from flask import current_app, session
from flask_login import current_user

from extensions import db
from helpers import (
    _user_can_access_accounting,
    clinicas_do_usuario,
    ensure_veterinarian_membership,
    has_professional_access,
    has_veterinarian_profile,
    is_veterinarian,
)
from template_filters import whatsapp_chat_url
from time_utils import utcnow

# Performance: cache for context processor results (short TTL)
_context_cache = {}
_CONTEXT_CACHE_TTL = 30  # seconds


def _get_cached_context(user_id: int, key: str):
    """Get cached context value if not expired."""
    cache_key = f"{user_id}:{key}"
    entry = _context_cache.get(cache_key)
    if entry is not None:
        value, timestamp = entry
        if _time_module.time() - timestamp < _CONTEXT_CACHE_TTL:
            return value
    return None


def _invalidate_cached_context(user_id: int, key: str) -> None:
    """Remove cached context value so the next request recomputes it.

    Usado ao marcar mensagens como lidas (ou aceitar consultas) para o badge
    da navbar atualizar imediatamente, sem esperar o TTL do cache.
    """
    _context_cache.pop(f"{user_id}:{key}", None)


def _invalidate_admin_unread_cache() -> None:
    """Invalida o contador de mensagens não lidas de todos os admins."""
    from models import User

    try:
        for admin in User.query.filter_by(role='admin').all():
            _invalidate_cached_context(admin.id, 'unread_messages')
    except Exception:
        pass


def _set_cached_context(user_id: int, key: str, value):
    """Cache context value with timestamp."""
    cache_key = f"{user_id}:{key}"
    _context_cache[cache_key] = (value, _time_module.time())
    # Cleanup old entries periodically (keep cache small)
    if len(_context_cache) > 500:
        now = _time_module.time()
        expired = [k for k, (_, ts) in list(_context_cache.items())
                   if now - ts > _CONTEXT_CACHE_TTL * 2]
        for k in expired:
            _context_cache.pop(k, None)
    return value


def _invalidate_admin_action_cache(user_id: int | None = None) -> None:
    from models import User

    try:
        if user_id:
            _invalidate_cached_context(user_id, 'admin_action_notifications')
            return
        for admin in User.query.filter_by(role='admin').all():
            _invalidate_cached_context(admin.id, 'admin_action_notifications')
    except Exception:
        pass


def inject_unread_count():
    from models import Message, User

    try:
        if getattr(current_user, "is_authenticated", False):
            user_id = current_user.id
            cached = _get_cached_context(user_id, 'unread_messages')
            if cached is not None:
                return dict(unread_messages=cached)

            if current_user.role == 'admin':
                admin_ids = [u.id for u in User.query.filter_by(role='admin').all()]
                unread = (
                    Message.query
                    .filter(Message.receiver_id.in_(admin_ids), Message.lida.is_(False))
                    .count()
                )
            else:
                unread = (
                    Message.query
                    .filter_by(receiver_id=current_user.id, lida=False)
                    .count()
                )
            _set_cached_context(user_id, 'unread_messages', unread)
        else:
            unread = 0
    except Exception:
        db.session.rollback()
        unread = 0
    return dict(unread_messages=unread)


def inject_admin_action_notifications():
    from models import AdminActionNotification

    try:
        if (
            getattr(current_user, "is_authenticated", False)
            and (getattr(current_user, 'role', '') or '').lower() == 'admin'
        ):
            cached = _get_cached_context(current_user.id, 'admin_action_notifications')
            if cached is not None:
                return cached

            open_count = (
                AdminActionNotification.query
                .filter_by(recipient_user_id=current_user.id)
                .filter(AdminActionNotification.status.in_(['unread', 'read']))
                .count()
            )
            unread_count = (
                AdminActionNotification.query
                .filter_by(recipient_user_id=current_user.id, status='unread')
                .count()
            )
            recent = (
                AdminActionNotification.query
                .filter_by(recipient_user_id=current_user.id)
                .filter(AdminActionNotification.status.in_(['unread', 'read']))
                .order_by(AdminActionNotification.created_at.desc())
                .limit(5)
                .all()
            )
            payload = dict(
                admin_action_count=open_count,
                admin_action_unread_count=unread_count,
                admin_action_recent=recent,
            )
            _set_cached_context(current_user.id, 'admin_action_notifications', payload)
            return payload
    except Exception:
        db.session.rollback()
    return dict(
        admin_action_count=0,
        admin_action_unread_count=0,
        admin_action_recent=[],
    )


def inject_pending_exam_count():
    """Exames aguardando ação do veterinário (status 'pending').

    O badge reflete itens acionáveis: ele zera quando o exame é confirmado,
    não quando a página é visitada (sem aritmética de "visto", que gerava
    notificações fantasma).
    """
    try:
        if getattr(current_user, "is_authenticated", False) and is_veterinarian(current_user):
            user_id = current_user.id
            cached = _get_cached_context(user_id, 'pending_exam_count')
            if cached is not None:
                return dict(pending_exam_count=cached)

            from models import ExamAppointment

            pending = ExamAppointment.query.filter_by(
                specialist_id=current_user.veterinario.id, status='pending'
            ).count()
            _set_cached_context(user_id, 'pending_exam_count', pending)
        else:
            pending = 0
    except Exception:
        db.session.rollback()
        pending = 0
    return dict(pending_exam_count=pending)


def inject_pending_appointment_count():
    """Consultas futuras aguardando aceite do veterinário.

    Usa o MESMO escopo da página da Agenda (consultas do veterinário ou
    criadas por ele), para o badge bater exatamente com o que a página
    mostra. O badge zera quando a consulta é aceita/atendida — sem
    aritmética de "visto".
    """

    from sqlalchemy import or_

    try:
        if getattr(current_user, "is_authenticated", False) and is_veterinarian(current_user):
            user_id = current_user.id
            cached = _get_cached_context(user_id, 'pending_appointment_count')
            if cached is not None:
                return dict(pending_appointment_count=cached)

            from models import Appointment

            now = utcnow()
            scope_conditions = [
                Appointment.veterinario_id == current_user.veterinario.id,
            ]
            scope_conditions.append(Appointment.created_by == user_id)
            pending = Appointment.query.filter(
                Appointment.status == "scheduled",
                Appointment.scheduled_at > now,
                or_(*scope_conditions),
            ).count()
            _set_cached_context(user_id, 'pending_appointment_count', pending)
        else:
            pending = 0
    except Exception:
        db.session.rollback()
        pending = 0
    return dict(pending_appointment_count=pending)


def _clinic_pending_appointments_query(veterinario):
    """Return query for scheduled clinic appointments excluding the given vet."""
    if not veterinario or not getattr(veterinario, "clinica_id", None):
        return None

    from models import Appointment

    return Appointment.query.filter(
        Appointment.clinica_id == veterinario.clinica_id,
        Appointment.status == "scheduled",
        Appointment.veterinario_id != veterinario.id,
    )


def inject_clinic_pending_appointment_count():
    """Expose count of scheduled appointments in the clinic excluding the current vet."""

    # getattr: em renders fora de request (ou testes com _get_user=None) o
    # current_user pode não ser um objeto flask-login completo.
    if getattr(current_user, "is_authenticated", False) and is_veterinarian(current_user):
        user_id = current_user.id
        cached = _get_cached_context(user_id, 'clinic_pending_appointment_count')
        if cached is not None:
            seen = session.get("clinic_pending_seen_count", 0)
            return dict(clinic_pending_appointment_count=max(cached - seen, 0))

        pending_query = _clinic_pending_appointments_query(
            getattr(current_user, "veterinario", None)
        )
        pending = pending_query.count() if pending_query is not None else 0
        _set_cached_context(user_id, 'clinic_pending_appointment_count', pending)
        seen = session.get("clinic_pending_seen_count", 0)
        pending = max(pending - seen, 0)
    else:
        pending = 0
    return dict(clinic_pending_appointment_count=pending)


def inject_veterinarian_membership_context():
    if not getattr(current_user, "is_authenticated", False):
        return dict(
            is_active_veterinarian=False,
            has_veterinarian_profile_flag=False,
            current_veterinarian_membership=None,
        )

    has_profile = has_veterinarian_profile(current_user)
    membership = None
    if has_profile:
        membership = ensure_veterinarian_membership(getattr(current_user, 'veterinario', None))

    return dict(
        is_active_veterinarian=has_profile and is_veterinarian(current_user),
        has_veterinarian_profile_flag=has_profile,
        has_professional_access=has_professional_access(current_user),
        current_veterinarian_membership=membership,
    )


def inject_clinic_invite_count():
    if getattr(current_user, "is_authenticated", False) and has_veterinarian_profile(current_user):
        user_id = current_user.id
        cached = _get_cached_context(user_id, 'pending_clinic_invites')
        if cached is not None:
            return dict(pending_clinic_invites=cached)

        from models import VetClinicInvite

        pending = VetClinicInvite.query.filter_by(
            veterinario_id=current_user.veterinario.id, status='pending'
        ).count()
        _set_cached_context(user_id, 'pending_clinic_invites', pending)
    else:
        pending = 0
    return dict(pending_clinic_invites=pending)


def inject_accounting_access_flag():
    return dict(can_access_accounting=_user_can_access_accounting())


def inject_has_clinic_access():
    """Expose whether the current user can access at least one clinic."""
    if not getattr(current_user, "is_authenticated", False):
        return dict(has_clinic_access=False)

    cached = _get_cached_context(current_user.id, 'has_clinic_access')
    if cached is not None:
        return dict(has_clinic_access=bool(cached))

    from models import Clinica

    has_clinic_access = (
        clinicas_do_usuario()
        .with_entities(Clinica.id)
        .limit(1)
        .first()
        is not None
    )
    _set_cached_context(current_user.id, 'has_clinic_access', has_clinic_access)
    return dict(has_clinic_access=has_clinic_access)


def inject_minha_casa_de_racao():
    """Expõe a casa de ração do usuário logado para os templates."""
    from models import CasaDeRacao

    if not getattr(current_user, "is_authenticated", False):
        return dict(minha_casa_de_racao=None)
    cached = _get_cached_context(current_user.id, 'minha_casa_de_racao')
    if cached is not None:
        return dict(
            minha_casa_de_racao=(
                SimpleNamespace(**cached)
                if cached
                else None
            )
        )
    casa = CasaDeRacao.query.filter_by(owner_id=current_user.id).first()
    if casa:
        cached_casa = {'id': casa.id, 'nome': casa.nome}
        _set_cached_context(current_user.id, 'minha_casa_de_racao', cached_casa)
        return dict(minha_casa_de_racao=SimpleNamespace(**cached_casa))
    _set_cached_context(current_user.id, 'minha_casa_de_racao', False)
    return dict(minha_casa_de_racao=None)


def inject_current_app():
    """Make current_app available in templates for view_functions checks."""
    return dict(current_app=current_app)


def inject_whatsapp_helpers():
    return dict(whatsapp_chat_url=whatsapp_chat_url)


def inject_site_flags():
    """Injeta feature flags do banco no contexto de todos os templates."""
    from models.base import SiteFlag
    try:
        flags = {
            'loja_em_breve': SiteFlag.get('loja_em_breve', default=True),
            'plano_saude_em_breve': SiteFlag.get('plano_saude_em_breve', default=True),
        }
    except Exception:
        db.session.rollback()
        flags = {'loja_em_breve': True, 'plano_saude_em_breve': True}
    return dict(site_flags=flags)


def inject_mp_public_key():
    """Disponibiliza a chave pública do Mercado Pago para os templates."""
    return dict(MERCADOPAGO_PUBLIC_KEY=current_app.config.get("MERCADOPAGO_PUBLIC_KEY"))


def inject_default_pickup_address():
    """Exposes DEFAULT_PICKUP_ADDRESS config to templates."""
    return dict(DEFAULT_PICKUP_ADDRESS=current_app.config.get("DEFAULT_PICKUP_ADDRESS"))


_PROCESSORS = (
    inject_unread_count,
    inject_admin_action_notifications,
    inject_pending_exam_count,
    inject_pending_appointment_count,
    inject_clinic_pending_appointment_count,
    inject_veterinarian_membership_context,
    inject_clinic_invite_count,
    inject_accounting_access_flag,
    inject_has_clinic_access,
    inject_minha_casa_de_racao,
    inject_current_app,
    inject_whatsapp_helpers,
    inject_site_flags,
    inject_mp_public_key,
    inject_default_pickup_address,
)


def register_context_processors(app):
    for func in _PROCESSORS:
        app.context_processor(func)
