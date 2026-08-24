import os

import pytest

from extensions import db
from models import User
from models.sfa import (
    SfaPaciente,
    SfaRespostaT0,
    SfaRespostaT10,
    SfaRespostaT30,
    SfaSinanLog,
)
from services import sfa_service
from services.sfa_service import T0_CONSENT_ACCEPTED


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess.clear()
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_sfa_dashboard_requires_auth_or_token(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "0")
    monkeypatch.delenv("SFA_ADMIN_TOKEN", raising=False)
    app.config["TESTING"] = False

    response = client.get("/sfa/")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_sfa_dashboard_allows_admin_session(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "0")
    monkeypatch.delenv("SFA_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("SFA_SHEET_ID_SINAN", "sheet-sfa-test")
    monkeypatch.setenv("SFA_SHEET_GID_SINAN", "12345")
    app.config["TESTING"] = False

    with app.app_context():
        admin = User(name="Admin", email="admin-sfa@test", password_hash="x", role="admin")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)
    response = client.get("/sfa/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Planilha de origem" in html
    assert 'href="https://docs.google.com/spreadsheets/d/sheet-sfa-test/edit#gid=12345"' in html


def test_sfa_dashboard_allows_admin_token(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "0")
    monkeypatch.setenv("SFA_ADMIN_TOKEN", "token-sfa-teste")
    app.config["TESTING"] = False

    response = client.get("/sfa/", headers={"X-SFA-Token": "token-sfa-teste"})

    assert response.status_code == 200


def test_sfa_dashboard_filters_by_symptom_month(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "1")
    app.config["TESTING"] = False

    with app.app_context():
        db.session.add_all(
            [
                SfaPaciente(id_estudo="SFA-MAR", nome="Paciente Marco", grupo="A"),
                SfaPaciente(id_estudo="SFA-ABR", nome="Paciente Abril", grupo="B"),
                SfaPaciente(id_estudo="SFA-SINAN-MAR", nome="Paciente SINAN Marco", grupo="A"),
            ]
        )
        db.session.add_all(
            [
                SfaRespostaT0(id_estudo="SFA-MAR", data_inicio_sintomas="18/03/2026"),
                SfaRespostaT0(id_estudo="SFA-ABR", data_inicio_sintomas="02/04/2026"),
                SfaSinanLog(
                    id_estudo_vinculado="SFA-SINAN-MAR",
                    data_inicio_sintomas="20/03/2026",
                    chave_dedup="sinan-mar-dashboard",
                ),
            ]
        )
        db.session.commit()

    response = client.get("/sfa/?mes=2026-03")

    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "value=\"2026-03\"" in html
    assert "03/2026" in html
    assert "Total no cadastro" in html
    assert "mes_inicio_sintomas=2026-03" in html
    assert "Paciente Abril" not in html

    patient_response = client.get("/sfa/pacientes?mes_inicio_sintomas=2026-03")
    patient_html = patient_response.data.decode("utf-8")
    assert "Paciente Marco" in patient_html
    assert "Paciente SINAN Marco" in patient_html
    assert "Paciente Abril" not in patient_html


def test_sfa_webhook_requires_secret_outside_testing(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "0")
    monkeypatch.delenv("SFA_WEBHOOK_SECRET", raising=False)
    app.config["TESTING"] = False

    response = client.post("/sfa/webhook/t0", json={})

    # Requisições JSON recebem o 403 sanitizado para 404 (não vazar existência).
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("stage", "submitter_name", "response_model"),
    [
        ("t0", "on_submit_t0", SfaRespostaT0),
        ("t10", "on_submit_t10", SfaRespostaT10),
        ("t30", "on_submit_t30", SfaRespostaT30),
    ],
)
def test_sfa_webhook_legado_autenticado_retorna_410_sem_gravar(
    app,
    client,
    monkeypatch,
    stage,
    submitter_name,
    response_model,
):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "0")
    monkeypatch.setenv("SFA_WEBHOOK_SECRET", "segredo-webhook")
    app.config["TESTING"] = False
    submitter_calls = []
    monkeypatch.setattr(
        sfa_service,
        submitter_name,
        lambda dados: submitter_calls.append(dados) or {"ok": True},
    )

    with app.app_context():
        count_before = response_model.query.count()

    response = client.post(
        f"/sfa/webhook/{stage}",
        json={
            "id_estudo": "SFA-001",
            "nome": "Participante Teste",
            "data_nascimento": "2000-01-01",
            "aceite_tcle": [T0_CONSENT_ACCEPTED],
        },
        headers={"X-SFA-Secret": "segredo-webhook"},
    )

    assert response.status_code == 410
    assert response.get_json() == {
        "ok": False,
        "error": "legacy_form_disabled",
        "stage": stage,
        "message": "O formulario legado foi desativado. Use o formulario essencial do participante.",
    }
    assert submitter_calls == []
    with app.app_context():
        assert response_model.query.count() == count_before


def test_sfa_sync_flashes_detailed_error_message(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "0")
    monkeypatch.delenv("SFA_ADMIN_TOKEN", raising=False)
    app.config["TESTING"] = False

    with app.app_context():
        admin = User(name="Admin Sync", email="admin-sync@test", password_hash="x", role="admin")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)
    monkeypatch.setattr(
        "services.sfa_service.sincronizar_sinan",
        lambda: {
            "novos": 0,
            "erros": 1,
            "mensagem": "Falha ao ler Google Sheets: Credenciais Google nao configuradas.",
        },
    )
    monkeypatch.setattr(
        "services.sfa_service.sincronizar_respostas_t0",
        lambda: (_ for _ in ()).throw(
            AssertionError("sincronizacao T0 legada nao deve ser executada")
        ),
    )

    response = client.post("/sfa/sync")

    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert (
        "warning",
        "Falha ao ler Google Sheets: Credenciais Google nao configuradas.",
    ) in flashes


def test_sfa_rotina_manual_nao_sincroniza_t0_legado(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "0")
    monkeypatch.delenv("SFA_ADMIN_TOKEN", raising=False)
    app.config["TESTING"] = False

    with app.app_context():
        admin = User(
            name="Admin Rotina",
            email="admin-rotina@test",
            password_hash="x",
            role="admin",
        )
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)
    monkeypatch.setattr(
        sfa_service,
        "sincronizar_respostas_t0",
        lambda: (_ for _ in ()).throw(
            AssertionError("sincronizacao T0 legada nao deve ser executada")
        ),
    )
    monkeypatch.setattr(
        sfa_service,
        "verificar_seguimento",
        lambda: {"atrasados_t10": ["SFA-10"], "atrasados_t30": []},
    )

    response = client.post("/sfa/rotina")

    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert (
        "info",
        "Rotina concluída: 1 T10 atrasados, 0 T30 atrasados.",
    ) in flashes
    assert all("T0 importada" not in message for _category, message in flashes)


def test_sfa_rotina_diaria_preserva_sinan_e_seguimento_sem_sync_t0(app, monkeypatch):
    monkeypatch.setattr(
        sfa_service,
        "sincronizar_respostas_t0",
        lambda: (_ for _ in ()).throw(
            AssertionError("sincronizacao T0 legada nao deve ser executada")
        ),
    )
    monkeypatch.setattr(
        sfa_service,
        "sincronizar_sinan",
        lambda: {"novos": 2, "erros": 0},
    )
    monkeypatch.setattr(
        sfa_service,
        "verificar_seguimento",
        lambda: {"atrasados_t10": ["SFA-10"], "atrasados_t30": ["SFA-30"]},
    )

    resultado = sfa_service.rodar_rotina_diaria(app)

    assert resultado == {
        "novos": 2,
        "erros": 0,
        "atrasados_t10": ["SFA-10"],
        "atrasados_t30": ["SFA-30"],
    }
