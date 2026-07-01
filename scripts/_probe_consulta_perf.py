"""Temporary read-only probe for the /consulta/<id> perf investigation.

Simulates an authenticated GET to /consulta/4523 as an existing vet user to
exercise the deployed profiling instrumentation (PERF_PROFILE / PERF_LOAD_USER
log lines) without needing to wait for organic traffic. Animal 4523 already
has an in_progress consulta for clinica_id=1 (verified via read-only query),
so this does NOT create any new row or otherwise mutate data.
"""
import time
from app_factory import create_app

app = create_app()

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True
    start = time.perf_counter()
    resp = client.get("/consulta/4523")
    elapsed = time.perf_counter() - start
    print("status:", resp.status_code, "bytes:", len(resp.data), "elapsed_ms:", round(elapsed * 1000, 1))
