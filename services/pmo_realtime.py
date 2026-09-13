"""Serviço em memória de eventos em tempo real para o Vacina PMO.

Mantém um buffer circular thread-safe (deque maxlen=500) com identificadores
monotônicos para delta polling ultra-leve (< 1ms por consulta, zero queries ao
banco durante polling rotineiro).

Compatível com o dyno Heroku (1 worker Gunicorn gthread com 4 threads).
"""
from collections import deque
import threading
import time
from typing import Any

_lock = threading.Lock()
_events: deque[dict[str, Any]] = deque(maxlen=500)
_event_seq = 0


def record_pmo_event(event_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Registra um novo evento na fila circular e incrementa o ID sequencial."""
    global _event_seq
    with _lock:
        _event_seq += 1
        event = {
            'id': _event_seq,
            'type': str(event_type or '').strip(),
            'data': dict(data or {}),
            'timestamp': time.time(),
        }
        _events.append(event)
        return event


def get_pmo_events_since(
    since_id: int | None = None,
    sheet_gid: str | None = None,
) -> dict[str, Any]:
    """Retorna eventos ocorridos desde `since_id`.
    
    Se `since_id` for None ou negativo, inicializa a escuta retornando o ID mais
    recente sem devolver o histórico antigo (evita reprocessamento na abertura).
    
    Se `since_id` for maior que o ID atual (ex: servidor reiniciou), retorna
    `reset: True` para orientar o cliente a recarregar o estado completo.
    """
    with _lock:
        latest_id = _event_seq

        # Inicialização: cliente quer apenas saber a posição atual do ponteiro
        if since_id is None or since_id < 0:
            return {
                'reset': False,
                'latest_id': latest_id,
                'events': [],
            }

        # Servidor reiniciou ou contador foi zerado
        if since_id > latest_id:
            return {
                'reset': True,
                'latest_id': latest_id,
                'events': [],
            }

        # Buffer circular transbordou e o cliente ficou muito para trás
        if _events and since_id < _events[0]['id'] - 1:
            return {
                'reset': True,
                'latest_id': latest_id,
                'events': [],
            }

        target_gid = str(sheet_gid or '').strip()
        matching: list[dict[str, Any]] = []
        for ev in _events:
            if ev['id'] > since_id:
                ev_gid = str(ev.get('data', {}).get('sheet_gid') or '').strip()
                # Entrega se o evento for para a mesma aba ou se não tiver aba restrita
                if not target_gid or not ev_gid or ev_gid == target_gid:
                    matching.append(ev)

        return {
            'reset': False,
            'latest_id': latest_id,
            'events': matching,
        }


def reset_pmo_events_for_testing() -> None:
    """Zera o buffer de eventos e a sequência (usado exclusivamente em testes)."""
    global _event_seq
    with _lock:
        _events.clear()
        _event_seq = 0
