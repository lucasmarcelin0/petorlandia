"""Modo SCHEDULER_IN_WEB: os jobs do dyno scheduler rodando dentro do web."""

import importlib.util
import pathlib

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

import scheduler


EXPECTED_JOB_IDS = {
    'monthly-accounting-backfill',
    'pmo-sheet-sync',
    'pmo-doses-compile',
    'mercadopago-membership-reconciliation',
    'atlas-artefatos',
    'lembretes-consultas-exames-vacinas',
    'lembretes-tratamento',
    'lembretes-recebimento',
    'lembretes-adocao',
    'lembretes-fim-trial',
    'winback-pos-trial',
    'carrinho-abandonado',
    'snapshot-financeiro',
    'mercadopago-oauth-renewal',
}


_real_stop_in_web = scheduler.stop_in_web


@pytest.fixture(autouse=True)
def _clean_web_scheduler(monkeypatch):
    monkeypatch.delenv('SCHEDULER_IN_WEB', raising=False)
    monkeypatch.delenv('ENABLE_WEB_SCHEDULER', raising=False)
    _real_stop_in_web()
    yield
    _real_stop_in_web()


def _load_gunicorn_conf():
    path = pathlib.Path(__file__).resolve().parents[1] / 'gunicorn.conf.py'
    spec = importlib.util.spec_from_file_location('gunicorn_conf_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_register_jobs_registra_todos_os_jobs_do_dyno():
    sched = BackgroundScheduler(timezone='UTC')
    scheduler.register_jobs(sched)
    assert {job.id for job in sched.get_jobs()} == EXPECTED_JOB_IDS


def test_main_usa_o_mesmo_conjunto_de_jobs(monkeypatch):
    captured = {}

    class FakeBlocking(BackgroundScheduler):
        def start(self, *args, **kwargs):
            captured['ids'] = {job.id for job in self.get_jobs()}

    monkeypatch.setattr(scheduler, 'BlockingScheduler', FakeBlocking)
    scheduler.main()
    assert captured['ids'] == EXPECTED_JOB_IDS


def test_desligado_por_padrao_nao_inicia_nada():
    assert scheduler.start_in_web() is None


def test_ligado_inicia_uma_vez_e_para(monkeypatch):
    monkeypatch.setenv('SCHEDULER_IN_WEB', '1')
    monkeypatch.setitem(scheduler.app.config, 'TESTING', False)
    registered = []

    def fake_register(sched):
        registered.append(sched)
        sched.add_job(lambda: None, 'interval', hours=24, id='dummy')

    monkeypatch.setattr(scheduler, 'register_jobs', fake_register)

    first = scheduler.start_in_web()
    assert first is not None and first.running
    assert scheduler.start_in_web() is first
    assert len(registered) == 1
    assert first.get_job('dummy').misfire_grace_time == 300

    scheduler.stop_in_web()
    assert scheduler._web_scheduler is None


def test_nao_duplica_com_o_modo_antigo(monkeypatch):
    monkeypatch.setenv('SCHEDULER_IN_WEB', '1')
    monkeypatch.setenv('ENABLE_WEB_SCHEDULER', '1')
    monkeypatch.setitem(scheduler.app.config, 'TESTING', False)
    monkeypatch.setattr(scheduler, 'register_jobs', lambda s: pytest.fail('não deveria registrar'))
    assert scheduler.start_in_web() is None


def test_gancho_do_gunicorn_nao_faz_nada_com_a_chave_desligada(monkeypatch):
    conf = _load_gunicorn_conf()
    monkeypatch.setattr(scheduler, 'start_in_web', lambda: pytest.fail('chave desligada'))
    monkeypatch.setattr(scheduler, 'stop_in_web', lambda: pytest.fail('chave desligada'))
    conf.post_worker_init(worker=None)
    conf.worker_exit(server=None, worker=None)


def test_gancho_do_gunicorn_inicia_e_nunca_derruba_o_worker(monkeypatch):
    conf = _load_gunicorn_conf()
    monkeypatch.setenv('SCHEDULER_IN_WEB', '1')
    calls = []

    class Log:
        def exception(self, msg):
            calls.append(('log', msg))

    class Worker:
        log = Log()

    monkeypatch.setattr(scheduler, 'start_in_web', lambda: calls.append('start'))
    conf.post_worker_init(Worker())
    assert calls == ['start']

    def boom():
        raise RuntimeError('falhou')

    monkeypatch.setattr(scheduler, 'start_in_web', boom)
    conf.post_worker_init(Worker())  # não propaga a exceção
    assert calls[-1][0] == 'log'


def test_jobs_de_intervalo_caem_em_horarios_fixos_apos_reinicio():
    """Reiniciar o processo não adia os jobs de intervalo (worker reciclado)."""
    from datetime import datetime, timezone

    fire_times = []
    for _ in range(2):  # dois "boots" seguidos
        sched = BackgroundScheduler(timezone='UTC')
        scheduler.register_jobs(sched)
        for job_id in ('pmo-sheet-sync', 'mercadopago-membership-reconciliation'):
            trigger = sched.get_job(job_id).trigger
            now = datetime(2026, 10, 20, 22, 7, 31, tzinfo=timezone.utc)
            fire_times.append((job_id, trigger.get_next_fire_time(None, now)))
    assert fire_times[0] == fire_times[2] and fire_times[1] == fire_times[3]
    assert fire_times[0][1].minute == 10 and fire_times[0][1].second == 0
    assert fire_times[1][1].minute == 30 and fire_times[1][1].second == 0
