import os
import sys
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from admin import ClinicaAdmin, CasaDeRacaoAdminView  # noqa: E402
from models import Clinica, CasaDeRacao, db  # noqa: E402
import app as app_module  # noqa: E402


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


@pytest.mark.parametrize('view_class,model_class,folder', [
    (ClinicaAdmin, Clinica, 'clinicas'),
    (CasaDeRacaoAdminView, CasaDeRacao, 'casas_de_racao'),
])
@pytest.mark.parametrize('clean', [False, True])
def test_admin_uploads_processed_logo(monkeypatch, app, view_class, model_class, folder, clean):
    image = Image.new('RGBA', (3, 1), (190, 190, 190, 255))
    image.putpixel((1, 0), (0, 0, 0, 0))
    image.putpixel((2, 0), (255, 0, 0, 255))
    stream = BytesIO()
    image.save(stream, format='PNG')
    stream.seek(0)
    file = FileStorage(stream=stream, filename='logo.webp', content_type='image/webp')

    def capture(upload, filename, **kwargs):
        assert kwargs['folder'] == folder
        assert filename.endswith('_logo.png')
        assert upload.content_type == 'image/png'
        saved = Image.open(upload.stream)
        assert saved.mode == 'RGB'
        assert saved.getpixel((0, 0)) == ((255, 255, 255) if clean else (190, 190, 190))
        assert saved.getpixel((1, 0)) == (255, 255, 255)
        assert saved.getpixel((2, 0)) == (255, 0, 0)
        return 'http://processed-logo'

    monkeypatch.setattr(app_module, 'upload_to_s3', capture)
    form = SimpleNamespace(
        logotipo_upload=SimpleNamespace(data=file),
        logo_clean_background=SimpleNamespace(data=clean),
    )
    model = model_class(nome='Test')
    view_class(model_class, db.session).on_model_change(form, model, True)
    assert model.logotipo == 'http://processed-logo'

