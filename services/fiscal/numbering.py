"""Serviço de numeração fiscal com controle de concorrência.

Por que esse arquivo é sensível:
    O número da NFS-e é SEQUENCIAL por emissor/tipo/série. Se dois threads
    (ex: dois workers do Celery processando orçamentos em paralelo) reservarem
    o mesmo número, a prefeitura REJEITA a segunda emissão como "RPS duplicado"
    e a primeira pode ser cancelada acidentalmente. Pior: se os dois
    insistirem, o contador vai "pular" números, deixando gaps que a Receita
    questiona.

    A versão anterior tinha `while True` sem teto de retries — sob carga
    concorrente, um conflito persistente travaria o worker indefinidamente
    sem log. Aqui:

      - Lock forte em PostgreSQL via `SELECT ... FOR UPDATE` (row-level).
      - Retry com teto e backoff exponencial + jitter para SQLite
        ("database is locked") e conflitos de INSERT-inicial.
      - Falha explícita após o teto, com mensagem auditável.
"""

from __future__ import annotations

import random
import time
from typing import Union

from sqlalchemy.exc import IntegrityError, InvalidRequestError, OperationalError

from extensions import db
from models import FiscalCounter, FiscalDocumentType


# Retries antes de desistir. Empiricamente: com 4 workers simultâneos e
# tempo médio de reserva <5ms, a probabilidade de 8 colisões seguidas
# no mesmo counter é desprezível (<1e-9). Se chegar aqui é bug real.
_MAX_RETRIES = 8

# Backoff exponencial: 5ms → 10ms → 20ms → 40ms → 80ms → 160ms → 320ms → 640ms
_INITIAL_BACKOFF_SECONDS = 0.005


class NumberingReservationError(RuntimeError):
    """Levantada quando não conseguimos reservar número fiscal após _MAX_RETRIES.

    O chamador deve interromper a emissão e logar — NÃO deve tentar
    novamente sozinho sem um circuit breaker, ou vai piorar o problema.
    """


def _normalize_doc_type(doc_type: FiscalDocumentType | str) -> FiscalDocumentType:
    if isinstance(doc_type, FiscalDocumentType):
        return doc_type
    try:
        return FiscalDocumentType[str(doc_type).upper()]
    except KeyError as exc:  # pragma: no cover - validação defensiva
        raise ValueError(f"Tipo de documento fiscal inválido: {doc_type}") from exc


def _sleep_with_backoff(attempt: int) -> None:
    """Backoff exponencial com jitter (±25%) para dessincronizar retries
    de múltiplos workers colidindo no mesmo counter."""
    base = _INITIAL_BACKOFF_SECONDS * (2 ** attempt)
    jitter = base * random.uniform(-0.25, 0.25)
    time.sleep(base + jitter)


def reserve_next_number(
    emitter_id: int,
    doc_type: Union[FiscalDocumentType, str],
    series: str,
) -> int:
    """Reserve o próximo número fiscal com lock por emissor/tipo/série.

    Args:
        emitter_id: FK do FiscalEmitter dono do counter.
        doc_type:   NFSE / NFE (aceita enum ou string).
        series:     série numérica da nota ("1" é o default da maioria).

    Returns:
        O número reservado, único no tuple (emitter_id, doc_type, series).

    Raises:
        NumberingReservationError: se depois de _MAX_RETRIES não conseguir.
        ValueError: se doc_type for inválido.
    """
    normalized_type = _normalize_doc_type(doc_type)
    normalized_series = str(series or "1")
    session = db.session

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            # begin() para transação de nível 0, begin_nested() (SAVEPOINT)
            # se já estamos dentro de uma. Sem isso, emit_nfse_sync (que já
            # abre tx) quebra aqui com InvalidRequestError.
            try:
                transaction_ctx = session.begin()
            except InvalidRequestError:
                transaction_ctx = session.begin_nested()

            with transaction_ctx:
                counter = (
                    session.query(FiscalCounter)
                    .filter_by(
                        emitter_id=emitter_id,
                        doc_type=normalized_type,
                        series=normalized_series,
                    )
                    # with_for_update = SELECT ... FOR UPDATE no Postgres.
                    # No SQLite é no-op mas o lock do arquivo cobre.
                    .with_for_update()
                    .first()
                )
                if counter is None:
                    # Primeiro RPS dessa série — cria o counter. Aqui mora o
                    # conflito clássico: dois workers simultâneos veem None
                    # e ambos tentam INSERT. O unique constraint em
                    # (emitter_id, doc_type, series) faz um falhar — a gente
                    # pega o IntegrityError abaixo, dorme, e retenta; na
                    # segunda volta o counter já existe e vai pro UPDATE.
                    counter = FiscalCounter(
                        emitter_id=emitter_id,
                        doc_type=normalized_type,
                        series=normalized_series,
                        current_number=1,
                    )
                    session.add(counter)
                    session.flush()
                    return counter.current_number

                counter.current_number += 1
                session.flush()
                return counter.current_number

        except IntegrityError as exc:
            # Conflito de INSERT inicial — esperado e tratável.
            last_exc = exc
            session.rollback()
            _sleep_with_backoff(attempt)
            continue

        except OperationalError as exc:
            # SQLite "database is locked" ou deadlock em Postgres.
            # Retry é seguro pois não commitamos ainda.
            last_exc = exc
            session.rollback()
            _sleep_with_backoff(attempt)
            continue

    # Esgotou retries. Não mascara o bug — levanta com contexto.
    raise NumberingReservationError(
        f"Falha ao reservar número fiscal após {_MAX_RETRIES} tentativas "
        f"(emitter_id={emitter_id}, doc_type={normalized_type.value}, "
        f"series={normalized_series}). Última causa: {last_exc!r}"
    ) from last_exc
