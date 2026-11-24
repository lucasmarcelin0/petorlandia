"""Sincronização ao vivo entre a aba do dia e o painel /vacina-pmo.

Até 24/11/2026 a aba só voltava ao banco quando alguém apertava
"Sincronizar" (o sync agendado roda num dyno que fica desligado). Se a equipe
reordenava ou editava linhas, o banco ficava com os números antigos e a trava
de identidade recusava — com razão, mas em silêncio — gravar o que o painel
marcava. Aqui ficam os dois sentidos que faltavam:

* **planilha → painel**: enquanto algum painel está aberto numa aba, ele
  consulta ``/vacina-pmo/updates`` a cada poucos segundos. Uma vez a cada
  ``PMO_LIVE_CHECK_SECONDS`` por aba, o servidor lê as células (uma chamada da
  API) e, se mudaram desde a última leitura, aplica a aba como o botão
  "Sincronizar" faz e avisa os painéis abertos (evento ``sheet_synced``);
* **painel → planilha**: a gravação continua imediata; quando a trava recusa
  ou a API falha, ``request_tab_sync`` agenda o sync da aba, que realinha as
  linhas e regrava o que o painel tinha e a planilha não.

Tudo roda em threads do próprio processo web (1 worker gunicorn). Um lock por
aba garante que dois syncs da mesma aba nunca se sobreponham; pedidos que
chegam durante um sync são agrupados num único sync seguinte.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable

from flask import current_app

_state_lock = threading.Lock()
_tab_locks: dict[str, threading.RLock] = {}
_last_check: dict[str, float] = {}
_last_hash: dict[str, str] = {}
_checking: set[str] = set()
_pending: dict[str, dict[str, Any]] = {}
_local = threading.local()

MAX_RERUNS = 3


def _env_seconds(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


def check_interval() -> float:
    return _env_seconds("PMO_LIVE_CHECK_SECONDS", 15)


def debounce_seconds() -> float:
    return _env_seconds("PMO_LIVE_DEBOUNCE_SECONDS", 1.5)


def enabled(app=None) -> bool:
    app = app or current_app
    if os.getenv("PMO_LIVE_SHEET_SYNC", "").strip().lower() in {"0", "false", "off", "nao", "não"}:
        return False
    return bool(app.config.get("PMO_LIVE_SHEET_SYNC", not app.testing))


def tab_lock(sheet_gid: str) -> threading.RLock:
    with _state_lock:
        return _tab_locks.setdefault(str(sheet_gid), threading.RLock())


def in_sync() -> bool:
    """Este thread está aplicando uma aba (as gravações dele não reagendam)."""
    return bool(getattr(_local, "active", False))


@contextmanager
def applying(sheet_gid: str):
    """Segura o lock da aba e marca o thread como aplicando a aba."""
    with tab_lock(sheet_gid):
        previous = getattr(_local, "active", False)
        _local.active = True
        try:
            yield
        finally:
            _local.active = previous


def values_hash(values: list[list[Any]]) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _spawn(app, name: str, job: Callable[[], None]) -> None:
    """Roda ``job`` fora da request; nos testes, ``PMO_LIVE_SYNC_INLINE`` roda na hora."""
    if app.config.get("PMO_LIVE_SYNC_INLINE"):
        job()
        return

    def runner():
        with app.app_context():
            try:
                job()
            finally:
                from extensions import db
                db.session.remove()

    threading.Thread(target=runner, name=name, daemon=True).start()


def sync_tab_now(sheet_gid: str, sheet_title: str = "", *, tab=None, reason: str = "") -> bool:
    """Lê (se preciso) e aplica a aba; devolve True se o painel mudou.

    Segura o lock da aba. Nunca roda na aba mestre, que é compilada à parte.
    """
    from services import vacina_pmo_service as servico

    sheet_gid = str(sheet_gid or "").strip()
    if not sheet_gid:
        return False
    with applying(sheet_gid):
        try:
            if tab is None:
                sheet_title = day_tab_title(sheet_gid)
                if not sheet_title:
                    return False
                tab = servico.read_vacina_pmo_tab(sheet_gid=sheet_gid, sheet_title=sheet_title)
            if not tab.sheet_gid or str(tab.sheet_gid) != sheet_gid or servico._pmo_is_master_sheet(tab.sheet_title):
                return False
            before = servico.get_saved_vacina_pmo_rows(sheet_gid=sheet_gid).get("rows")
            rows = servico.parse_vacina_pmo_rows(tab.values)
            servico.persist_vacina_pmo_rows(
                rows,
                spreadsheet_id=tab.spreadsheet_id,
                sheet_gid=tab.sheet_gid,
                sheet_title=tab.sheet_title,
                park_orphans=True,
            )
            with _state_lock:
                _last_hash[sheet_gid] = values_hash(tab.values)
            after = servico.get_saved_vacina_pmo_rows(sheet_gid=sheet_gid).get("rows")
        except Exception:
            from extensions import db
            db.session.rollback()
            current_app.logger.warning(
                "PMO ao vivo: falha ao sincronizar a aba %s (%s)", sheet_gid, reason, exc_info=True
            )
            return False

    changed = json.dumps(before, sort_keys=True, default=str) != json.dumps(after, sort_keys=True, default=str)
    if changed:
        current_app.logger.info("PMO ao vivo: aba %s sincronizada (%s)", sheet_gid, reason or "-")
        try:
            from services.pmo_realtime import record_pmo_event
            record_pmo_event("sheet_synced", {"sheet_gid": sheet_gid, "reason": reason})
        except Exception:
            current_app.logger.warning("PMO ao vivo: falha ao avisar os painéis", exc_info=True)
    return changed


def day_tab_title(sheet_gid: str) -> str:
    """Título da aba se ela for uma aba de dia ("DD/MM/AAAA"); senão vazio.

    Só as abas de dia entram na sincronização ao vivo: a aba mestre e as listas
    de inscrição são grandes e têm rotinas próprias.
    """
    from services import vacina_pmo_service as servico

    for sheet in servico.list_vacina_pmo_sheets():
        if str(sheet.get("gid")) == str(sheet_gid):
            title = sheet.get("title") or ""
            if sheet.get("date") and not servico._pmo_is_master_sheet(title):
                return title
            return ""
    return ""


def check_tab_for_changes(sheet_gid: str) -> bool:
    """Lê a aba; se as células mudaram desde a última leitura, aplica."""
    from services import vacina_pmo_service as servico

    title = day_tab_title(sheet_gid)
    if not title:
        return False
    tab = servico.read_vacina_pmo_tab(sheet_gid=sheet_gid, sheet_title=title)
    digest = values_hash(tab.values)
    with _state_lock:
        if _last_hash.get(str(sheet_gid)) == digest:
            return False
    return sync_tab_now(sheet_gid, tab=tab, reason="planilha mudou")


def maybe_check_tab(sheet_gid: str) -> bool:
    """Chamado pelo polling dos painéis; no máximo uma leitura por intervalo por aba."""
    sheet_gid = str(sheet_gid or "").strip()
    if not sheet_gid or not enabled():
        return False
    now = time.monotonic()
    with _state_lock:
        if sheet_gid in _checking or now - _last_check.get(sheet_gid, -1e9) < check_interval():
            return False
        _last_check[sheet_gid] = now
        _checking.add(sheet_gid)
    app = current_app._get_current_object()

    def job():
        try:
            check_tab_for_changes(sheet_gid)
        except Exception:
            current_app.logger.warning("PMO ao vivo: falha ao conferir a aba %s", sheet_gid, exc_info=True)
        finally:
            with _state_lock:
                _checking.discard(sheet_gid)

    _spawn(app, f"pmo-live-check-{sheet_gid}", job)
    return True


def request_tab_sync(sheet_gid: str, sheet_title: str = "", *, reason: str = "") -> bool:
    """Agenda o sync da aba; pedidos em sequência viram um sync só."""
    sheet_gid = str(sheet_gid or "").strip()
    if not sheet_gid or in_sync() or not enabled():
        return False
    with _state_lock:
        pending = _pending.get(sheet_gid)
        if pending is not None:
            pending["dirty"] = True
            return True
        _pending[sheet_gid] = {"dirty": False}
    app = current_app._get_current_object()

    def job():
        try:
            if not app.config.get("PMO_LIVE_SYNC_INLINE"):
                time.sleep(debounce_seconds())
            for _ in range(MAX_RERUNS):
                with _state_lock:
                    _pending[sheet_gid]["dirty"] = False
                sync_tab_now(sheet_gid, sheet_title, reason=reason)
                with _state_lock:
                    if not _pending[sheet_gid]["dirty"]:
                        break
        finally:
            with _state_lock:
                _pending.pop(sheet_gid, None)

    _spawn(app, f"pmo-live-sync-{sheet_gid}", job)
    return True


def reset_state() -> None:
    """Só para testes."""
    with _state_lock:
        _last_check.clear()
        _last_hash.clear()
        _checking.clear()
        _pending.clear()
