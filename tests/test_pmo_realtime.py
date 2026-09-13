# -*- coding: utf-8 -*-
"""Testes da sincronização em tempo real do Vacina PMO (multi-usuários/telas).

Garante que quando um usuário altera status, nome ou anexa uma foto a um animal,
outros usuários visualizando a mesma aba recebam os eventos em tempo real
sem necessidade de recarregar a página, com zero esgotamento de threads.
"""
from __future__ import annotations

import io
from pathlib import Path
import pytest

from extensions import db
from models import PmoVaccinationVisit, User
from services.pmo_realtime import (
    get_pmo_events_since,
    record_pmo_event,
    reset_pmo_events_for_testing,
)
from services.vacina_pmo_service import persist_vacina_pmo_rows


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "vacina_pmo" / "dashboard.html"


def _pmo_login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _setup_animal(sheet_gid, role="vacinador", email="realtime_vacinador@example.com"):
    user = User(name="Vacinador Realtime", email=email, role=role)
    user.set_password("senha")
    db.session.add(user)
    persist_vacina_pmo_rows(
        [
            {
                "id": "visit-rt-1",
                "status": "pendente",
                "tutor": "Tutor Realtime",
                "address": "Rua das Flores, 100",
                "phone1": "5516999998888",
                "phone2": "",
                "dogs": 1,
                "cats": 0,
                "animals": [{"name": "Rex", "species": "cao", "status": "pendente"}],
                "note": "",
                "date": "2026-09-13",
                "shift": "Manha",
                "password": "PMORT100",
                "certificateUrl": "",
                "sourceRow": 2,
            }
        ],
        spreadsheet_id="sheet-test-rt",
        sheet_gid=sheet_gid,
        sheet_title="13/09/2026",
    )
    db.session.commit()
    visit = PmoVaccinationVisit.query.filter_by(sheet_gid=sheet_gid).one()
    return user.id, visit.animals[0].id


def _dummy_image_bytes():
    from PIL import Image

    stream = io.BytesIO()
    Image.new("RGB", (32, 24), color=(60, 120, 180)).save(stream, format="JPEG")
    return stream.getvalue()


# ─── Testes de Unidade do Serviço pmo_realtime ───────────────────────────────


def test_record_and_get_pmo_events():
    reset_pmo_events_for_testing()

    ev1 = record_pmo_event("photo_updated", {"animal_id": 10, "sheet_gid": "gid_a"})
    ev2 = record_pmo_event("status_updated", {"animal_id": 10, "status": "vacinado", "sheet_gid": "gid_a"})

    assert ev1["id"] == 1
    assert ev2["id"] == 2
    assert ev1["type"] == "photo_updated"
    assert ev2["type"] == "status_updated"

    # since_id=None (inicialização do cliente)
    init_res = get_pmo_events_since(None)
    assert init_res["reset"] is False
    assert init_res["latest_id"] == 2
    assert init_res["events"] == []

    # since_id=0 (pega todos)
    res_all = get_pmo_events_since(0)
    assert res_all["reset"] is False
    assert res_all["latest_id"] == 2
    assert len(res_all["events"]) == 2

    # since_id=1 (pega apenas o ev2)
    res_delta = get_pmo_events_since(1)
    assert res_delta["latest_id"] == 2
    assert len(res_delta["events"]) == 1
    assert res_delta["events"][0]["id"] == 2


def test_pmo_events_filter_by_sheet():
    reset_pmo_events_for_testing()

    record_pmo_event("photo_updated", {"animal_id": 1, "sheet_gid": "gid_111"})
    record_pmo_event("status_updated", {"animal_id": 2, "sheet_gid": "gid_222"})
    record_pmo_event("sheet_synced", {"sheet_gid": "gid_111"})
    record_pmo_event("global_alert", {})

    res_111 = get_pmo_events_since(0, sheet_gid="gid_111")
    assert len(res_111["events"]) == 3  # ev1, ev3 e global_alert
    event_types_111 = [e["type"] for e in res_111["events"]]
    assert "status_updated" not in event_types_111

    res_222 = get_pmo_events_since(0, sheet_gid="gid_222")
    assert len(res_222["events"]) == 2  # ev2 e global_alert
    event_types_222 = [e["type"] for e in res_222["events"]]
    assert "photo_updated" not in event_types_222


def test_pmo_events_reset_on_out_of_bounds():
    reset_pmo_events_for_testing()
    record_pmo_event("test_ev", {"sheet_gid": "gid_1"})

    # Cliente envia since_id 50, mas servidor está no id 1 (ex: reinício)
    res = get_pmo_events_since(50)
    assert res["reset"] is True
    assert res["latest_id"] == 1
    assert res["events"] == []


def test_pmo_events_ring_buffer_overflow():
    reset_pmo_events_for_testing()
    for i in range(550):
        record_pmo_event("tick", {"idx": i})

    # Buffer de 500 itens: os primeiros 50 caíram
    res = get_pmo_events_since(0)
    assert res["reset"] is True  # Ficou muito para trás

    # Se pedir a partir de um ID ainda na janela (ex: 520)
    res_recent = get_pmo_events_since(520)
    assert res_recent["reset"] is False
    assert len(res_recent["events"]) == 30


# ─── Testes do Endpoint /vacina-pmo/updates ──────────────────────────────────


def test_updates_endpoint_requires_auth(client):
    res = client.get("/vacina-pmo/updates")
    assert res.status_code in (302, 401, 403)


def test_updates_endpoint_forbids_unauthorized_roles(client, app):
    with app.app_context():
        user = User(name="Cliente Comum", email="cliente_pmo@example.com", role="cliente")
        user.set_password("senha")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _pmo_login(client, user_id)
    res = client.get("/vacina-pmo/updates")
    # request_hooks mascara 403 em 404 para endpoints JSON para evitar vazamento
    assert res.status_code in (403, 404)


def test_updates_endpoint_returns_json_to_vacinador(client, app):
    with app.app_context():
        user_id, _ = _setup_animal("gid_updates_test", role="vacinador", email="vac_updates@example.com")
        reset_pmo_events_for_testing()
        record_pmo_event("ping", {"sheet_gid": "gid_updates_test"})

    _pmo_login(client, user_id)
    res = client.get("/vacina-pmo/updates?since=0&sheet_gid=gid_updates_test")
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["success"] is True
    assert payload["reset"] is False
    assert payload["latest_id"] >= 1
    assert len(payload["events"]) == 1
    assert payload["events"][0]["type"] == "ping"


# ─── Testes de Emissão Automática de Eventos ──────────────────────────────────


def test_animal_status_mutation_emits_event(client, app):
    with app.app_context():
        user_id, pmo_animal_id = _setup_animal("gid_status_emit", role="admin", email="admin_status@example.com")
        reset_pmo_events_for_testing()

    _pmo_login(client, user_id)
    res = client.post(
        f"/vacina-pmo/animal/{pmo_animal_id}/status",
        json={"status": "vacinado"},
    )
    assert res.status_code == 200

    # Verifica se o evento foi gravado na fila de tempo real
    updates_res = client.get("/vacina-pmo/updates?since=0&sheet_gid=gid_status_emit")
    assert updates_res.status_code == 200
    updates_data = updates_res.get_json()
    events = updates_data["events"]
    assert any(
        e["type"] == "status_updated" and e["data"].get("animal_id") == pmo_animal_id
        for e in events
    )


def test_animal_name_mutation_emits_event(client, app):
    with app.app_context():
        user_id, pmo_animal_id = _setup_animal("gid_name_emit", role="admin", email="admin_name@example.com")
        reset_pmo_events_for_testing()

    _pmo_login(client, user_id)
    res = client.post(
        f"/vacina-pmo/animal/{pmo_animal_id}/name",
        json={"name": "Rex Furioso"},
    )
    assert res.status_code == 200

    updates_res = client.get("/vacina-pmo/updates?since=0&sheet_gid=gid_name_emit")
    assert updates_res.status_code == 200
    updates_data = updates_res.get_json()
    events = updates_data["events"]
    assert any(
        e["type"] == "animal_name_updated" and e["data"].get("name") == "Rex Furioso"
        for e in events
    )


def test_animal_photo_upload_emits_event(client, app, monkeypatch):
    with app.app_context():
        user_id, pmo_animal_id = _setup_animal("gid_photo_emit", role="vacinador", email="vac_photo@example.com")
        reset_pmo_events_for_testing()

    # Mock do upload S3
    monkeypatch.setattr("blueprints.vacina_pmo.upload_to_s3", lambda f, n, **kw: f"https://s3.fake/{n}")

    _pmo_login(client, user_id)
    photo_data = _dummy_image_bytes()
    res = client.post(
        f"/vacina-pmo/animal/{pmo_animal_id}/photo",
        data={"photo": (io.BytesIO(photo_data), "foto_rex.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True

    updates_res = client.get("/vacina-pmo/updates?since=0&sheet_gid=gid_photo_emit")
    assert updates_res.status_code == 200
    updates_data = updates_res.get_json()
    events = updates_data["events"]
    assert any(
        e["type"] == "photo_updated"
        and e["data"].get("animal_id") == pmo_animal_id
        and "https://s3.fake/" in e["data"].get("image_url", "")
        for e in events
    )


# ─── Testes do Template do Dashboard ─────────────────────────────────────────


def test_dashboard_template_contains_realtime_sync():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert ".pmo-photo-fresh-update" in html
    assert "pmoPulseGlow" in html
    assert 'data-animal-id="' in html
    assert "pollRealtimeUpdates" in html
    assert "scheduleNextRealtimePoll" in html
    assert "BroadcastChannel" in html
    assert "/vacina-pmo/updates" in html
