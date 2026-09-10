# -*- coding: utf-8 -*-
"""A foto do campo entra, e quando nao entra o vacinador fica sabendo por que.

Bug de campo (10/09/2026): a estagiaria nao conseguia enviar foto nenhuma na
aba de vacinacao e ninguem sabia dizer o motivo -- a tela mostrava so um selo
vermelho na miniatura, e a fila local reenviava o mesmo arquivo para sempre.

Duas causas se escondiam atras do mesmo selo:

1. o servidor so aceitava JPEG/PNG/WebP, e o iPhone no modo "Alta eficiencia"
   manda HEIC (a conversao do navegador falha calada em quem nao decodifica o
   formato -- o `catch` devolve o arquivo original);
2. erro definitivo (formato recusado, perfil sem permissao) era tratado como
   falha de conexao e voltava para a fila de retentativa.

Estes testes fixam o contrato dos dois lados: o servidor converte o que da
para converter e diz `retryable: false` no que nao adianta repetir; a tela
para de retentar, mostra o motivo e oferece o reenvio manual.
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from extensions import db
from models import PmoVaccinationVisit, User
from services.photo_intake import (
    UnsupportedPhotoFormat,
    ensure_heif_support,
    normalize_photo_upload,
    normalized_filename,
)
from services.vacina_pmo_service import persist_vacina_pmo_rows


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "vacina_pmo" / "dashboard.html"


@pytest.fixture(scope="module")
def source():
    return TEMPLATE.read_text(encoding="utf-8")


def function_body(source, name):
    match = re.search(
        rf"(?:async\s+)?function\s+{re.escape(name)}\([^)]*\)\s*\{{(.*?)\n  \}}",
        source,
        re.S,
    )
    assert match, f"funcao {name} nao encontrada"
    return match.group(1)


def _image_bytes(format_name="JPEG", size=(64, 48)):
    stream = BytesIO()
    Image.new("RGB", size, color=(70, 130, 180)).save(stream, format=format_name)
    return stream.getvalue()


def _pmo_login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _pmo_row(**overrides):
    row = {
        "id": "sheet-1",
        "status": "pendente",
        "tutor": "Tutor Foto",
        "address": "Rua 1, 10, Centro",
        "phone1": "5516999999999",
        "phone2": "",
        "dogs": 1,
        "cats": 0,
        "animals": [{"name": "Lua", "species": "cao", "status": "pendente"}],
        "note": "",
        "date": "2026-06-18",
        "shift": "Manha",
        "password": "PMOA9999",
        "certificateUrl": "",
        "sourceRow": 2,
    }
    row.update(overrides)
    return row


def _setup_animal(sheet_gid, role="admin", email="foto@example.com"):
    user = User(name="Usuario Foto", email=email, role=role)
    user.set_password("senha")
    db.session.add(user)
    persist_vacina_pmo_rows(
        [_pmo_row()],
        spreadsheet_id="sheet-test",
        sheet_gid=sheet_gid,
        sheet_title="18/06/2026",
    )
    db.session.commit()
    visit = PmoVaccinationVisit.query.filter_by(sheet_gid=sheet_gid).one()
    return user.id, visit.animals[0].id


# --- servidor -------------------------------------------------------------


def test_heic_do_iphone_e_convertido_para_jpeg():
    assert ensure_heif_support(), "pillow-heif precisa estar instalado"

    photo = normalize_photo_upload(_image_bytes("HEIF"))

    assert photo.converted is True
    assert photo.content_type == "image/jpeg"
    assert normalized_filename("IMG_0042.HEIC", photo) == "IMG_0042.jpg"
    with Image.open(photo.stream) as converted:
        assert converted.format == "JPEG"
    photo.stream.seek(0)


def test_jpeg_passa_sem_reencodar():
    original = _image_bytes("JPEG")

    photo = normalize_photo_upload(original)

    assert photo.converted is False
    assert photo.content_type == "image/jpeg"
    assert photo.stream.getvalue() == original


def test_arquivo_que_nao_e_imagem_continua_recusado():
    with pytest.raises(Exception) as exc:
        normalize_photo_upload(b"not-an-image")
    assert "não é uma foto válida" in str(exc.value)


def test_formato_sem_decodificador_avisa_o_que_fazer(monkeypatch):
    def _explode(*_args, **_kwargs):
        raise OSError("cannot identify image file")

    monkeypatch.setattr("services.photo_intake.ImageOps.exif_transpose", _explode)

    with pytest.raises(UnsupportedPhotoFormat) as exc:
        normalize_photo_upload(_image_bytes("HEIF"))
    assert "JPG, PNG ou WebP" in exc.value.user_message


def test_upload_de_heic_pelo_endpoint_guarda_jpeg(app, client, monkeypatch):
    with app.app_context():
        user_id, pmo_animal_id = _setup_animal("heic-test")

    _pmo_login(client, user_id)
    enviados = {}

    def _fake_upload(file, filename, folder="uploads"):
        enviados["filename"] = filename
        enviados["content_type"] = getattr(file, "content_type", "")
        enviados["data"] = file.read()
        return f"https://bucket.example/{folder}/{filename}"

    monkeypatch.setattr("app.upload_to_s3", _fake_upload)

    response = client.post(
        f"/vacina-pmo/animal/{pmo_animal_id}/photo",
        data={"photo": (BytesIO(_image_bytes("HEIF")), "IMG_0042.HEIC")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["converted_from"] == "HEIF"
    # O que vai para o S3 precisa ser exibivel pelo navegador do tutor.
    assert enviados["filename"].endswith(".jpg")
    assert enviados["content_type"] == "image/jpeg"
    with Image.open(BytesIO(enviados["data"])) as stored:
        assert stored.format == "JPEG"


def test_erro_definitivo_diz_para_a_fila_nao_insistir(app, client):
    with app.app_context():
        user_id, pmo_animal_id = _setup_animal("retryable-test", email="foto-retry@example.com")

    _pmo_login(client, user_id)
    response = client.post(
        f"/vacina-pmo/animal/{pmo_animal_id}/photo",
        data={"photo": (BytesIO(b"not-an-image"), "arquivo.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["retryable"] is False


def test_perfil_sem_permissao_recebe_json_e_nao_html(app, client):
    with app.app_context():
        user = User(name="Estagiaria", email="estagiaria-foto@example.com", role="estagiario")
        user.set_password("senha")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _pmo_login(client, user_id)
    response = client.post(
        "/vacina-pmo/animal/1/photo",
        data={"photo": (BytesIO(_image_bytes()), "lua.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 403
    payload = response.get_json()
    assert payload is not None, "a tela envia por fetch e precisa de JSON legivel"
    assert payload["retryable"] is False
    assert "permissão" in payload["message"]


def test_camera_liberada_apenas_na_tela_do_vacinador(app, client):
    with app.app_context():
        user = User(name="Vacinador", email="vacinador-camera@example.com", role="vacinador")
        user.set_password("senha")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _pmo_login(client, user_id)
    dashboard = client.get("/vacina-pmo")
    outra = client.get("/vacina-pmo/painel")

    assert dashboard.status_code == 200
    assert "camera=(self)" in dashboard.headers["Permissions-Policy"]
    assert "microphone=()" in dashboard.headers["Permissions-Policy"]
    assert outra.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=(self)"


# --- tela -----------------------------------------------------------------


def test_falha_definitiva_para_de_retentar(source):
    upload = function_body(source, "uploadAnimalPhoto")
    assert "failure.permanent = payload.retryable === false" in upload

    defer = function_body(source, "deferredQueueRecord")
    assert "blocked: Boolean(error && error.permanent)" in defer

    process = function_body(source, "processQueuedPhotos")
    assert ".filter((record) => !record.blocked)" in process


def test_motivo_da_falha_chega_na_tela(source):
    queued = function_body(source, "uploadQueuedPhoto")
    assert "'failed'" in queued
    assert "showAppToast" in queued, "erro definitivo precisa aparecer, nao so no console"

    render = function_body(source, "renderAnimalPhotoControl")
    assert "animal.photoUploadError" in render
    assert "'failed'" in render


def test_foto_travada_pode_ser_reenviada_a_mao(source):
    retry = function_body(source, "retryBlockedPhoto")
    assert "blocked: false" in retry
    assert "scheduleLocalQueueProcessing(0)" in retry
    assert 'id="pmo-photo-retry"' in source


def test_seletor_sem_tipo_nao_barra_foto_boa(source):
    prepare = function_body(source, "prepareAnimalPhoto")
    assert "looksLikeImageFile(file)" in prepare
    body = function_body(source, "looksLikeImageFile")
    assert "application/octet-stream" in body


def test_fila_travada_nao_finge_que_esta_sincronizando(source):
    status = function_body(source, "refreshLocalQueueStatus")
    assert "blockedCount" in status
    assert "não foram enviadas" in status
