"""Quais ofertas já podem aparecer para o público.

Regra da casa: uma oferta só é anunciada quando existe de verdade. Vitrine
vazia — loja com produto de teste, "Banho & Tosa em breve" há meses, plano de
saúde que só coleta e-mail — custa mais confiança do que a ausência dela
economiza, e quem chega pela busca orgânica é justamente quem paga esse preço.

Cada função abaixo responde por uma oferta e volta a valer ``True`` sozinha no
momento em que houver oferta real cadastrada: o primeiro produto não-demo, o
primeiro plano de tosa ativo, o primeiro plano de saúde. Não há flag manual
para lembrar de ligar.

Admin enxerga tudo sempre (ver ``store_is_visible_for``): é quem cadastra a
primeira oferta e precisa conseguir chegar na tela para fazer isso.
"""

from __future__ import annotations

import time

from flask import current_app

#: A landing, o menu e o /servicos consultam estes gates a cada request. Sem
#: cache, cada visita anônima dispararia três EXISTS na base.
_CACHE_TTL_SECONDS = 300

_cache: dict[str, tuple[bool, float]] = {}


def _cached(key: str, resolver) -> bool:
    # Em teste cada caso monta seu próprio catálogo; um valor guardado do caso
    # anterior faria o resultado depender da ordem de execução.
    caching = not current_app.config.get('TESTING')

    now = time.monotonic()
    hit = _cache.get(key) if caching else None
    if hit is not None and now - hit[1] < _CACHE_TTL_SECONDS:
        return hit[0]

    try:
        value = bool(resolver())
    except Exception:  # noqa: BLE001 — indisponibilidade de banco não derruba a página
        current_app.logger.warning(
            'Falha ao avaliar disponibilidade da oferta %s', key, exc_info=True
        )
        # Sem resposta confiável, o padrão é esconder: uma oferta oculta por
        # engano é um clique perdido; uma vitrine vazia é um cliente perdido.
        return False

    if caching:
        _cache[key] = (value, now)
    return value


def invalidate_cache() -> None:
    """Zera o cache. Usado pelos testes e após cadastrar a primeira oferta."""
    _cache.clear()


# --------------------------------------------------------------------------- loja


def _store_has_real_catalog() -> bool:
    from sqlalchemy import or_

    from models import CasaDeRacao, Product

    return (
        Product.query
        .outerjoin(CasaDeRacao, Product.casa_de_racao_id == CasaDeRacao.id)
        .filter(Product.status == 'active')
        .filter(Product.is_demo.is_(False))
        .filter(
            or_(
                Product.casa_de_racao_id.is_(None),
                CasaDeRacao.status == 'ativa',
            )
        )
        .first()
    ) is not None


def store_is_public() -> bool:
    """A loja tem ao menos um produto real e vendável de um vendedor aprovado."""
    return _cached('store', _store_has_real_catalog)


def store_is_live() -> bool:
    """A loja está de fato aberta ao público?

    Junta as duas condições: existe catálogo real *e* o admin não escondeu a
    página à mão. É a resposta que o sitemap precisa — não faz sentido
    oferecer ao rastreador uma página que o visitante vê como "em breve".
    """
    return store_is_public() and not _manual_hold('loja_em_breve')


def health_plan_is_live() -> bool:
    """O plano de saúde está de fato aberto ao público?"""
    return health_plan_is_public() and not _manual_hold('plano_saude_em_breve')


def _manual_hold(flag_key: str) -> bool:
    from models.base import SiteFlag

    try:
        return bool(SiteFlag.get(flag_key, default=True))
    except Exception:  # noqa: BLE001
        return True


def store_is_visible_for(user) -> bool:
    """A loja aparece no menu e no sitemap para esta pessoa?

    Admin sempre vê — é quem aprova o primeiro produto e precisa da porta
    aberta para chegar lá.
    """
    if store_is_public():
        return True
    return _user_is_admin(user)


# ------------------------------------------------------------------ banho e tosa


def _grooming_has_active_plan() -> bool:
    from models import GroomingPlan

    return GroomingPlan.query.filter(GroomingPlan.active.is_(True)).first() is not None


def grooming_is_public() -> bool:
    """Existe ao menos um plano de banho e tosa ativo em alguma parceira."""
    return _cached('grooming', _grooming_has_active_plan)


# ---------------------------------------------------------------- plano de saúde


def _health_plan_exists() -> bool:
    from models import HealthPlan

    return HealthPlan.query.first() is not None


def health_plan_is_public() -> bool:
    """Existe ao menos um plano de saúde cadastrado com cobertura e preço."""
    return _cached('health_plan', _health_plan_exists)


# ----------------------------------------------------------------------- helpers


def _user_is_admin(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    role = getattr(user, 'role', None)
    return isinstance(role, str) and role.lower() == 'admin'
