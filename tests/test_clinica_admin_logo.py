import os
import sys
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from admin import ClinicaAdmin  # noqa: E402
from models import Clinica, db  # noqa: E402
import routes.app as app_module  # noqa: E402


@pytest.fixture
def app():
    app_module.app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    yield app_module.app


def make_file(filename: str = "logo.png") -> FileStorage:
    img = Image.new("RGB", (1, 1))
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return FileStorage(stream=buf, filename=filename, content_type="image/png")


def test_admin_saves_clinic_logo(monkeypatch, app):
    monkeypatch.setattr(app_module, "upload_to_s3", lambda *a, **k: "http://img")
    view = ClinicaAdmin(Clinica, db.session)
    form = SimpleNamespace(logotipo_upload=SimpleNamespace(data=make_file()))
    clinic = Clinica(nome="Test")
    view.on_model_change(form, clinic, True)
    assert clinic.logotipo == "http://img"


def test_admin_skips_empty_logo(monkeypatch, app):
    monkeypatch.setattr(app_module, "upload_to_s3", lambda *a, **k: "http://img")
    view = ClinicaAdmin(Clinica, db.session)
    form = SimpleNamespace(logotipo_upload=SimpleNamespace(data=make_file("")))
    clinic = Clinica(nome="Test", logotipo="existing")
    view.on_model_change(form, clinic, False)
    assert clinic.logotipo == "existing"
