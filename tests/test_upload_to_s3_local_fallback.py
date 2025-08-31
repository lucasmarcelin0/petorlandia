import os
import sys
from io import BytesIO
from PIL import Image
from werkzeug.datastructures import FileStorage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import app  # noqa: E402


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
