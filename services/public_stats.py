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
    # "1 clínica usando o sistema" responde sozinha a pergunta "alguém confia
    # nisso?" — e responde não. Abaixo do piso a métrica some, que é
    # exatamente o comportamento que este módulo promete.
    'clinicas': 5,
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
        # `status=ativa` significa cadastro aprovado, não uso real. A lista é
        # deliberadamente explícita para cadastros de teste nunca virarem
        # prova social por acidente.
        clinic_ids = current_app.config.get('PUBLIC_STATS_CLINIC_IDS', ())
        if isinstance(clinic_ids, str):
            clinic_ids = tuple(
                int(raw_id.strip())
                for raw_id in clinic_ids.split(',')
                if raw_id.strip().isdigit()
            )
        clinic_ids = tuple(clinic_ids or ())
        clinicas = (
            _count(
                Clinica,
                Clinica.status == 'ativa',
                Clinica.id.in_(clinic_ids),
            )
            if clinic_ids
            else 0
        )
        if clinicas >= THRESHOLDS['clinicas']:
            label = (
                'clínica usando o sistema'
                if clinicas == 1
                else 'clínicas usando o sistema'
            )
            stats.append(Stat(clinicas, label))
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
