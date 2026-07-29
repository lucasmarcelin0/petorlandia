"""Números reais de uso, para a prova social da landing.

Regra da casa: só publicamos um número quando ele já é grande o bastante para
somar credibilidade. "12 pets acompanhados" convence menos que não dizer nada,
então cada métrica tem um piso e some sozinha enquanto não o alcança.

Os números vêm do banco — nunca são estimados nem arredondados para cima.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from flask import current_app

#: Cache in-process: a landing é pública e recebe muito acesso; sem isso cada
#: visita dispararia três COUNT na base.
_CACHE_TTL_SECONDS = 900
_cache: dict[str, tuple[list, float]] = {}


@dataclass(frozen=True)
class Stat:
    value: int
    label: str


#: Piso por métrica. Abaixo disso a métrica não aparece.
THRESHOLDS = {
    'pets': 50,
    'vacinas': 100,
    'clinicas': 3,
}


def _count(model, *filters) -> int:
    from extensions import db

    query = db.session.query(model)
    for condition in filters:
        query = query.filter(condition)
    return query.count()


def _collect() -> list[Stat]:
    from models import Animal, Clinica, Vacina

    stats: list[Stat] = []

    try:
        pets = _count(Animal, Animal.removido_em.is_(None))
        if pets >= THRESHOLDS['pets']:
            stats.append(Stat(pets, 'pets acompanhados'))
    except Exception:  # noqa: BLE001
        current_app.logger.warning('Falha ao contar pets para a prova social', exc_info=True)

    try:
        vacinas = _count(Vacina, Vacina.aplicada.is_(True))
        if vacinas >= THRESHOLDS['vacinas']:
            stats.append(Stat(vacinas, 'vacinas registradas'))
    except Exception:  # noqa: BLE001
        current_app.logger.warning('Falha ao contar vacinas para a prova social', exc_info=True)

    try:
        clinicas = _count(Clinica)
        if clinicas >= THRESHOLDS['clinicas']:
            stats.append(Stat(clinicas, 'clínicas usando o sistema'))
    except Exception:  # noqa: BLE001
        current_app.logger.warning('Falha ao contar clínicas para a prova social', exc_info=True)

    return stats


def public_stats() -> list[Stat]:
    """Métricas prontas para exibição, ou lista vazia se nenhuma atingiu o piso."""

    cached = _cache.get('stats')
    if cached and (time.time() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    try:
        stats = _collect()
    except Exception:  # noqa: BLE001
        # Prova social nunca pode derrubar a landing.
        current_app.logger.exception('Falha ao montar prova social')
        stats = []

    _cache['stats'] = (stats, time.time())
    return stats


def reset_cache() -> None:
    """Usado em testes e após importações em massa."""

    _cache.clear()
