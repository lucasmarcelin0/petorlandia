"""Ganchos do gunicorn (lido automaticamente da raiz do projeto).

Não define nenhuma configuração: as opções continuam todas no Procfile.
Serve só para, com SCHEDULER_IN_WEB=1, iniciar os jobs do scheduler.py
dentro do worker web (veja docs/production_runbook.md). Com a chave
desligada (padrão) os ganchos não fazem nada.
"""

import os


def _web_mode_enabled() -> bool:
    value = os.getenv("SCHEDULER_IN_WEB", "")
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


def post_worker_init(worker):
    if not _web_mode_enabled():
        return
    try:
        import scheduler

        scheduler.start_in_web()
    except Exception:  # noqa: BLE001 - o site nunca pode cair por causa dos jobs
        worker.log.exception("[Scheduler] Falha ao iniciar os jobs dentro do web.")


def worker_exit(server, worker):
    if not _web_mode_enabled():
        return
    try:
        import scheduler

        scheduler.stop_in_web()
    except Exception:  # noqa: BLE001
        server.log.exception("[Scheduler] Falha ao parar os jobs dentro do web.")
