"""Efeitos da primeira mensalidade paga: medir a conversão e pagar a indicação.

O momento em que uma avaliação vira assinatura paga é o dado mais valioso do
funil e, até aqui, era o único que não deixava rastro. É também o gatilho do
programa de indicação: quem indicou só ganha o mês grátis quando o indicado
efetivamente paga — indicação que não vira cliente não gera custo.

Os dois efeitos ficam aqui, e não dentro da rotina que grava a cobrança, por
dois motivos: emitir evento e creditar assinatura exigem ``commit``, e a
gravação da cobrança acontece dentro de uma transação maior; e ambos precisam
ser idempotentes, porque o Mercado Pago reenvia a mesma notificação.
"""

from __future__ import annotations

from datetime import timedelta

from flask import current_app

from extensions import db
from services.product_analytics import track_event
from time_utils import utcnow

#: Meses grátis creditados a quem indicou, quando o indicado paga a primeira
#: mensalidade. Um mês é aproximadamente o CAC de uma clínica por indicação.
REFERRAL_REWARD_DAYS = 30

#: Dias extras de avaliação para quem chega por um link de indicação.
REFERRED_TRIAL_BONUS_DAYS = 15


def mark_converted(membership) -> bool:
    """Registra a primeira cobrança paga de uma assinatura. Idempotente.

    Só grava o campo — quem chama está dentro de uma transação e o efeito
    colateral acontece depois, em :func:`process_pending_conversions`.
    """
    if membership is None or membership.converted_at is not None:
        return False
    membership.converted_at = utcnow()
    return True


def process_pending_conversions() -> int:
    """Emite ``trial_converted`` e credita indicações ainda não processadas.

    Chamada depois dos commits da reconciliação e do webhook. Devolve quantas
    conversões foram processadas nesta passagem.
    """
    from models import VeterinarianMembership

    pending = (
        VeterinarianMembership.query
        .filter(VeterinarianMembership.converted_at.isnot(None))
        .filter(VeterinarianMembership.conversion_processed_at.is_(None))
        .all()
    )
    if not pending:
        return 0

    processed = 0
    for membership in pending:
        user = getattr(getattr(membership, 'veterinario', None), 'user', None)
        try:
            track_event(
                'trial_converted',
                user_id=getattr(user, 'id', None),
                plan='veterinario',
                source_path='/veterinario/assinatura',
            )
            if user is not None:
                _grant_referral_reward(user)
        except Exception:  # noqa: BLE001 — nunca travar a reconciliação
            current_app.logger.exception(
                'Falha ao processar conversão da assinatura %s', membership.id
            )
        membership.conversion_processed_at = utcnow()
        processed += 1

    db.session.commit()
    return processed


def _grant_referral_reward(referred_user) -> bool:
    """Dá um mês grátis a quem indicou este usuário. Idempotente."""
    from models import ReferralSignup

    signup = ReferralSignup.query.filter_by(
        referred_user_id=referred_user.id
    ).first()
    if signup is None or signup.rewarded_at is not None:
        return False

    referrer = getattr(getattr(signup, 'code', None), 'user', None)
    membership = _membership_for(referrer)
    if membership is None:
        # Sem assinatura para creditar (indicador é tutor, por exemplo). Marca
        # como tratado para não reprocessar a cada reconciliação.
        signup.rewarded_at = utcnow()
        db.session.add(signup)
        return False

    now = utcnow()
    from models import VeterinarianMembership

    paid_until = VeterinarianMembership._as_timezone_aware(membership.paid_until)
    base = paid_until if paid_until and paid_until > now else now
    membership.paid_until = base + timedelta(days=REFERRAL_REWARD_DAYS)
    signup.rewarded_at = now
    db.session.add_all([membership, signup])

    _notify_referrer(referrer, referred_user)
    return True


def _membership_for(user):
    veterinario = getattr(user, 'veterinario', None)
    return getattr(veterinario, 'membership', None) if veterinario else None


def _notify_referrer(referrer, referred_user) -> None:
    from services.notifications import notify_user

    primeiro_nome = (getattr(referrer, 'name', '') or '').split(' ')[0] or 'tudo bem'
    indicado = (getattr(referred_user, 'name', '') or 'quem você indicou').split(' ')[0]
    try:
        notify_user(
            referrer,
            'Sua indicação virou cliente — um mês por nossa conta',
            (
                f'Olá {primeiro_nome}! {indicado} assinou a PetOrlândia pelo seu link '
                'de indicação.\n\n'
                'Como combinado, adicionamos 30 dias à sua assinatura — não haverá '
                'cobrança nesse período.\n\n'
                'Obrigado por indicar. Cada clínica que entra deixa a rede mais útil '
                'para todo mundo.'
            ),
            kind='referral_rewarded',
        )
    except Exception:  # noqa: BLE001 — o crédito vale mesmo sem o aviso
        current_app.logger.exception('Falha ao avisar indicador sobre recompensa')
