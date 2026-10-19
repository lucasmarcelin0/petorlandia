import os
import sys
from io import BytesIO

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import app  # noqa: E402


@pytest.fixture(autouse=True)
def _app_context():
    """``upload_to_s3`` lê ``current_app.config`` (limite de tamanho e permissão
    do fallback local). Sem contexto de aplicação o helper cai no ``except`` e
    devolve ``None``, e o teste falha por um motivo que não é o que ele mede.
    """
    with app.app.app_context():
        app.app.config["TESTING"] = True
        yield


def test_upload_to_s3_falls_back_to_local(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "BUCKET", None)
    monkeypatch.setattr(app, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(app, "_s3", lambda: None)

    img_bytes = BytesIO()
    Image.new("RGB", (1, 1)).save(img_bytes, format="PNG")
    img_bytes.seek(0)
    fs = FileStorage(stream=img_bytes, filename="logo.png", content_type="image/png")

    url = app.upload_to_s3(fs, "logo.png", folder="clinicas")

    expected = tmp_path / "static" / "uploads" / "clinicas" / "logo.jpg"
    assert expected.exists()
    assert url == "/static/uploads/clinicas/logo.jpg"


def test_upload_to_s3_falls_back_on_error(tmp_path, monkeypatch):
    class DummyS3:
        def upload_fileobj(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(app, "BUCKET", "test-bucket")
    monkeypatch.setattr(app, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(app, "_s3", lambda: DummyS3())

    img_bytes = BytesIO()
    Image.new("RGB", (1, 1)).save(img_bytes, format="PNG")
    img_bytes.seek(0)
    fs = FileStorage(stream=img_bytes, filename="logo.png", content_type="image/png")

    url = app.upload_to_s3(fs, "logo.png", folder="clinicas")

    expected = tmp_path / "static" / "uploads" / "clinicas" / "logo.jpg"
    assert expected.exists()
    assert url == "/static/uploads/clinicas/logo.jpg"


def _png_transparente():
    img_bytes = BytesIO()
    imagem = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    imagem.paste((200, 30, 30, 255), (10, 5, 30, 15))
    imagem.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    return FileStorage(stream=img_bytes, filename="logo.png", content_type="image/png")


def test_logotipo_transparente_continua_transparente(tmp_path, monkeypatch):
    """Logo com fundo transparente não pode ganhar fundo branco no upload."""
    monkeypatch.setattr(app, "BUCKET", None)
    monkeypatch.setattr(app, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(app, "_s3", lambda: None)

    url = app.upload_to_s3(_png_transparente(), "logo.png", folder="clinicas", keep_transparency=True)

    assert url == "/static/uploads/clinicas/logo.png"
    with Image.open(tmp_path / "static" / "uploads" / "clinicas" / "logo.png") as salvo:
        assert salvo.format == "PNG"
        salvo = salvo.convert("RGBA")
        assert salvo.getpixel((0, 0))[3] == 0  # canto continua transparente
        assert salvo.getpixel((20, 10)) == (200, 30, 30, 255)


def test_sem_keep_transparency_segue_achatando_em_jpeg(tmp_path, monkeypatch):
    """Fotos e produtos continuam em JPEG com fundo branco, como antes."""
    monkeypatch.setattr(app, "BUCKET", None)
    monkeypatch.setattr(app, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(app, "_s3", lambda: None)

    url = app.upload_to_s3(_png_transparente(), "logo.png", folder="clinicas")

    assert url == "/static/uploads/clinicas/logo.jpg"
    with Image.open(tmp_path / "static" / "uploads" / "clinicas" / "logo.jpg") as salvo:
        # Fundo branco (com folga para a compressão do JPEG).
        assert min(salvo.getpixel((0, 0))[:3]) >= 240


def test_logotipo_sem_transparencia_continua_jpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "BUCKET", None)
    monkeypatch.setattr(app, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(app, "_s3", lambda: None)

    img_bytes = BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(img_bytes, format="PNG")
    img_bytes.seek(0)
    fs = FileStorage(stream=img_bytes, filename="logo.png", content_type="image/png")

    url = app.upload_to_s3(fs, "logo.png", folder="clinicas", keep_transparency=True)
    assert url == "/static/uploads/clinicas/logo.jpg"
