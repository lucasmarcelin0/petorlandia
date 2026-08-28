"""Contratos de resiliencia do painel de vacinacao usado em campo."""

import re
from pathlib import Path

import pytest


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "vacina_pmo" / "dashboard.html"


@pytest.fixture(scope="module")
def source():
    return TEMPLATE.read_text(encoding="utf-8")


def function_body(source, name):
    match = re.search(
        rf"(?:async\s+)?function\s+{re.escape(name)}\([^)]*\)\s*\{{(.*?)\n  \}}",
        source,
        re.S,
    )
    assert match, f"funcao {name} nao encontrada"
    return match.group(1)


def test_status_is_persisted_before_background_delivery(source):
    body = function_body(source, "queueAnimalStatusUpdate")
    assert "saveQueuedStatus(record)" in body
    assert "setAnimalQueuedStatus(record" in body
    assert "scheduleLocalQueueProcessing(0)" in body
    assert body.index("saveQueuedStatus(record)") < body.index("scheduleLocalQueueProcessing(0)")
    assert "localStorage.setItem(STATUS_QUEUE_STORAGE_KEY" in source


def test_pending_status_and_photo_are_restored_after_reload(source):
    assert "async function hydrateLocalQueues()" in source
    assert "hydrateQueuedPhotos(), hydrateQueuedStatuses()" in source
    assert "render();\n  hydrateLocalQueues();" in source
    assert source.count("hydrateLocalQueues();") >= 4
    assert "statusSaveUpdatedAt" in function_body(source, "replaceStateRow")


def test_retries_use_backoff_and_bounded_concurrency(source):
    assert "const QUEUE_RETRY_BASE_MS = 2500" in source
    assert "const QUEUE_RETRY_MAX_MS" in source
    assert "const PHOTO_UPLOAD_CONCURRENCY = 2" in source
    assert "const STATUS_UPLOAD_CONCURRENCY = 3" in source
    assert "nextAttemptAt: Date.now() + queueRetryDelay(attempts)" in source
    assert "Number(record.nextAttemptAt || 0) <= now" in source
    assert "window.setTimeout(processQueuedPhotos, 0)" not in source


def test_last_local_change_wins_over_late_responses(source):
    delete_photo = function_body(source, "deleteQueuedPhoto")
    delete_status = function_body(source, "deleteQueuedStatus")
    assert "Number(current.updatedAt) === Number(expectedUpdatedAt)" in delete_photo
    assert "Number(current.updatedAt) !== Number(expectedUpdatedAt)" in delete_status
    replace = function_body(source, "replaceStateRow")
    assert "animal.status = oldAnimal.status" in replace


def test_status_requests_fail_fast_but_keep_the_local_record(source):
    save = function_body(source, "saveAnimalStatus")
    assert "controller.abort(), 12000" in save
    assert "a alteração continua salva neste aparelho" in save
    upload = function_body(source, "uploadQueuedStatus")
    assert "deferQueuedStatus(record, error)" in upload
    assert "deleteQueuedStatus(animalId, record.updatedAt)" in upload


def test_interface_explains_offline_and_pending_state(source):
    assert 'id="pmo-connectivity"' in source
    assert "Sem internet." in source
    assert "serão enviadas automaticamente" in source
    assert 'class="pmo-status-sync"' in source
    assert "Foto guardada no aparelho" in source
