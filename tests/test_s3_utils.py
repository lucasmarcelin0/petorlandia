import os
import sys
from io import BytesIO

from werkzeug.datastructures import FileStorage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import s3_utils  # noqa: E402


def test_upload_to_s3_without_bucket(monkeypatch, caplog):
    caplog.set_level("WARNING")
    monkeypatch.setattr(s3_utils, "BUCKET_NAME", "")

    class DummyS3:
        def upload_fileobj(self, *_args, **_kwargs):
            raise AssertionError("upload_fileobj should not be called when bucket is missing")

    monkeypatch.setattr(s3_utils, "s3", DummyS3())

    file_storage = FileStorage(stream=BytesIO(b"data"), filename="logo.png", content_type="image/png")
    url = s3_utils.upload_to_s3(file_storage, "logo.png", folder="clinicas")

    assert url is None
    assert "S3 bucket is not configured" in caplog.text
