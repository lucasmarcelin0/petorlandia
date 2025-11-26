import os
import shutil
import sys
from io import BytesIO
from werkzeug.datastructures import FileStorage
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import app  # noqa: E402


def test_upload_to_s3_uses_content_type(monkeypatch):
    monkeypatch.setattr(app, "BUCKET", "test-bucket")

    captured = {}

    class DummyS3:
        def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None):
            captured['bucket'] = bucket
            captured['key'] = key
            captured['extra'] = ExtraArgs

    monkeypatch.setattr(app, "_s3", lambda: DummyS3())

    img_bytes = BytesIO()
    Image.new('RGB', (1, 1)).save(img_bytes, format='PNG')
    img_bytes.seek(0)

    fs = FileStorage(stream=img_bytes, filename='logo.png', content_type='image/png')
    url = app.upload_to_s3(fs, 'logo.png', folder='clinicas')

    assert captured['bucket'] == 'test-bucket'
    assert captured['key'].startswith('clinicas/logo.jpg')
    assert captured['extra']['ContentType'] == 'image/jpeg'
    assert 'ACL' not in captured['extra']
    assert url == f"https://test-bucket.s3.amazonaws.com/{captured['key']}"


def test_upload_to_s3_secure_filename(monkeypatch):
    monkeypatch.setattr(app, "BUCKET", "test-bucket")

    captured = {}

    class DummyS3:
        def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None):
            captured['key'] = key

    monkeypatch.setattr(app, "_s3", lambda: DummyS3())

    img_bytes = BytesIO()
    Image.new('RGB', (1, 1)).save(img_bytes, format='PNG')
    img_bytes.seek(0)

    fs = FileStorage(stream=img_bytes, filename='../evil image.png', content_type='image/png')
    url = app.upload_to_s3(fs, '../evil image.png', folder='clinicas')

    assert captured['key'].startswith('clinicas/evil_image.jpg')
    assert url == f"https://test-bucket.s3.amazonaws.com/{captured['key']}"


def test_upload_to_s3_falls_back_when_client_fails(tmp_path, monkeypatch):
    class DummyS3:
        def upload_fileobj(self, *args, **kwargs):
            raise RuntimeError("client failure")

    uploads_root = tmp_path / "static" / "uploads"
    expected_path = uploads_root / "clinicas" / "logo.jpg"

    monkeypatch.setattr(app, "BUCKET", "test-bucket")
    monkeypatch.setattr(app, "BUCKET_NAME", "test-bucket", raising=False)
    monkeypatch.setattr(app, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(app, "_s3", lambda: DummyS3())

    img_bytes = BytesIO()
    Image.new("RGB", (1, 1)).save(img_bytes, format="PNG")
    img_bytes.seek(0)

    fs = FileStorage(stream=img_bytes, filename="logo.png", content_type="image/png")

    try:
        url = app.upload_to_s3(fs, "logo.png", folder="clinicas")

        assert expected_path.exists()
        with Image.open(expected_path) as saved:
            assert saved.format == "JPEG"
            assert saved.size == (1, 1)

        assert url in {None, "/static/uploads/clinicas/logo.jpg"}
        if url is not None:
            assert url == "/static/uploads/clinicas/logo.jpg"
    finally:
        shutil.rmtree(uploads_root.parent, ignore_errors=True)
