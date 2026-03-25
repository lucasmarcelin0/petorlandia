import json

import pytest

from services.sfa_service import (
    _discover_local_google_credentials_file,
    _load_google_credentials_info,
)


SERVICE_ACCOUNT_INFO = {
    "type": "service_account",
    "project_id": "petorlandia-test",
    "private_key_id": "abc123",
    "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
    "client_email": "svc@petorlandia-test.iam.gserviceaccount.com",
    "client_id": "1234567890",
    "token_uri": "https://oauth2.googleapis.com/token",
}


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_google_credentials_info_uses_env_file(monkeypatch, tmp_path):
    creds_path = tmp_path / "service-account.json"
    _write_json(creds_path, SERVICE_ACCOUNT_INFO)
    monkeypatch.setenv("SFA_GOOGLE_CREDENTIALS_FILE", str(creds_path))
    monkeypatch.delenv("SFA_GOOGLE_CREDENTIALS_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    info = _load_google_credentials_info(project_root=tmp_path)

    assert info["client_email"] == SERVICE_ACCOUNT_INFO["client_email"]


def test_load_google_credentials_info_auto_detects_single_service_account(monkeypatch, tmp_path):
    _write_json(tmp_path / "sfao-490521-bc2dc5933745.json", SERVICE_ACCOUNT_INFO)
    _write_json(tmp_path / "other.json", {"cache": True})
    monkeypatch.delenv("SFA_GOOGLE_CREDENTIALS_FILE", raising=False)
    monkeypatch.delenv("SFA_GOOGLE_CREDENTIALS_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    info = _load_google_credentials_info(project_root=tmp_path)

    assert info["project_id"] == SERVICE_ACCOUNT_INFO["project_id"]
    assert (
        _discover_local_google_credentials_file(project_root=tmp_path).name
        == "sfao-490521-bc2dc5933745.json"
    )


def test_load_google_credentials_info_supports_google_application_credentials(monkeypatch, tmp_path):
    creds_path = tmp_path / "google-creds.json"
    _write_json(creds_path, SERVICE_ACCOUNT_INFO)
    monkeypatch.delenv("SFA_GOOGLE_CREDENTIALS_FILE", raising=False)
    monkeypatch.delenv("SFA_GOOGLE_CREDENTIALS_JSON", raising=False)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_path))

    info = _load_google_credentials_info(project_root=tmp_path)

    assert info["client_email"] == SERVICE_ACCOUNT_INFO["client_email"]


def test_discover_google_credentials_file_requires_explicit_choice_when_multiple_exist(monkeypatch, tmp_path):
    _write_json(tmp_path / "a.json", SERVICE_ACCOUNT_INFO)
    _write_json(
        tmp_path / "b.json",
        {**SERVICE_ACCOUNT_INFO, "client_email": "other@petorlandia-test.iam.gserviceaccount.com"},
    )
    monkeypatch.delenv("SFA_GOOGLE_CREDENTIALS_FILE", raising=False)
    monkeypatch.delenv("SFA_GOOGLE_CREDENTIALS_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    with pytest.raises(RuntimeError, match="Multiplos arquivos de credenciais Google encontrados"):
        _load_google_credentials_info(project_root=tmp_path)
