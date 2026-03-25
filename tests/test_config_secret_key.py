from config import _load_secret_key


def test_load_secret_key_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "env-secret")

    assert _load_secret_key(project_root=tmp_path) == "env-secret"


def test_load_secret_key_reads_existing_file(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    secret_file = tmp_path / "config" / "secret_key"
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text("file-secret\n", encoding="utf-8")

    assert _load_secret_key(project_root=tmp_path) == "file-secret"


def test_load_secret_key_creates_file_when_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRET_KEY", raising=False)

    secret = _load_secret_key(project_root=tmp_path)
    secret_file = tmp_path / "config" / "secret_key"

    assert secret
    assert secret_file.read_text(encoding="utf-8") == secret
