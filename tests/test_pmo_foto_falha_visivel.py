# -*- coding: utf-8 -*-
"""Nenhuma falha de foto fica muda -- nem a que "vai passar sozinha".

Bug de campo (12/09/2026): depois de arrumar o formato e a permissao, o
vacinador tirou a foto e continuou vendo so um selo vermelho. Ao tocar nele o
modal abria com "Tirar outra / Da galeria / Fechar" e nada mais -- nenhuma
explicacao, nenhum botao de reenviar.

Havia dois motivos, e os dois estao cobertos aqui:

1. a falha era classificada como `retryable` (erro 5xx do servidor), e so o
   estado `failed` mostrava o motivo. O `error` guardava a mensagem no
   IndexedDB e jogava fora ao pintar a tela;
2. `retryable` nao tinha limite: a foto repetia a mesma tentativa para sempre,
   entao nunca virava `failed` e o motivo nunca aparecia.

Do lado do servidor, uma falha do S3 virava `str(exc)` do boto3 na tela do
vacinador ("An error occurred (InvalidAccessKeyId)..."). Agora vira uma frase
em portugues, um `code` estavel e a decisao correta sobre retentar.
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import pytest

from extensions import db
from models import PmoVaccinationVisit, User
from services.photo_storage import PhotoStorageError, store_photo
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


def _image_bytes():
    from PIL import Image

    stream = BytesIO()
    Image.new("RGB", (32, 24), color=(70, 130, 180)).save(stream, format="JPEG")
    return stream.getvalue()


def _pmo_login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _setup_animal(sheet_gid, role="admin", email="falha@example.com"):
    user = User(name="Usuario Falha", email=email, role=role)
    user.set_password("senha")
    db.session.add(user)
    persist_vacina_pmo_rows(
        [
            {
                "id": "sheet-1",
                "status": "pendente",
                "tutor": "Tutor Falha",
                "address": "Rua 2, 20, Centro",
                "phone1": "5516999999999",
                "phone2": "",
                "dogs": 1,
                "cats": 0,
                "animals": [{"name": "Thor", "species": "cao", "status": "pendente"}],
                "note": "",
                "date": "2026-06-18",
                "shift": "Manha",
                "password": "PMOB9999",
                "certificateUrl": "",
                "sourceRow": 2,
            }
        ],
        spreadsheet_id="sheet-test",
        sheet_gid=sheet_gid,
        sheet_title="18/06/2026",
    )
    db.session.commit()
    visit = PmoVaccinationVisit.query.filter_by(sheet_gid=sheet_gid).one()
    return user.id, visit.animals[0].id


# --- traducao da falha de armazenamento -----------------------------------


class _ErroDoS3(Exception):
    def __init__(self, codigo):
        super().__init__(f"An error occurred ({codigo}) when calling the PutObject operation")
        self.response = {"Error": {"Code": codigo}}


def test_credencial_recusada_nao_manda_o_vacinador_tentar_para_sempre():
    def uploader(*_args, **_kwargs):
        raise _ErroDoS3("InvalidAccessKeyId")

    with pytest.raises(PhotoStorageError) as exc:
        store_photo(BytesIO(b"x"), "foto.jpg", uploader=uploader)

    assert exc.value.code == "credencial-recusada"
    # Repetir com a mesma chave da sempre no mesmo lugar: quem resolve e o
    # administrador, entao a tela precisa parar e dizer isso.
    assert exc.value.retryable is False
    assert "administrador" in exc.value.user_message
    # A mensagem crua do boto3 fica no `detail` (log), nao na frase da tela.
    assert "PutObject" not in exc.value.user_message
    assert "PutObject" in exc.value.detail


def test_falha_de_rede_continua_valendo_a_pena_tentar():
    class _SemRede(Exception):
        pass

    _SemRede.__name__ = "EndpointConnectionError"

    def uploader(*_args, **_kwargs):
        raise _SemRede("sem rota")

    with pytest.raises(PhotoStorageError) as exc:
        store_photo(BytesIO(b"x"), "foto.jpg", uploader=uploader)

    assert exc.value.code == "rede"
    assert exc.value.retryable is True


def test_bucket_nao_configurado_avisa_em_vez_de_fingir_que_guardou():
    with pytest.raises(PhotoStorageError) as exc:
        store_photo(BytesIO(b"x"), "foto.jpg", uploader=lambda *a, **k: None)

    assert exc.value.code == "sem-bucket"
    assert exc.value.retryable is False


def test_caminho_local_nao_conta_como_guardado():
    # No Heroku o disco some no proximo restart: dizer "salvou" seria mentira.
    with pytest.raises(PhotoStorageError) as exc:
        store_photo(BytesIO(b"x"), "foto.jpg", uploader=lambda *a, **k: "/static/uploads/foto.jpg")

    assert exc.value.code == "sem-durabilidade"
    assert exc.value.retryable is False


def test_envio_bem_sucedido_devolve_a_url():
    url = store_photo(
        BytesIO(b"x"),
        "foto.jpg",
        uploader=lambda *a, **k: "https://bucket.s3.amazonaws.com/animals/foto.jpg",
    )
    assert url == "https://bucket.s3.amazonaws.com/animals/foto.jpg"


# --- contrato da rota -----------------------------------------------------


def test_rota_devolve_motivo_legivel_quando_o_s3_recusa(app, client, monkeypatch):
    with app.app_context():
        user_id, pmo_animal_id = _setup_animal("s3-recusa", email="foto-s3@example.com")

    import app as app_module

    def _falha(*_args, **_kwargs):
        raise _ErroDoS3("AccessDenied")

    monkeypatch.setattr(app_module, "upload_to_s3", _falha)

    _pmo_login(client, user_id)
    response = client.post(
        f"/vacina-pmo/animal/{pmo_animal_id}/photo",
        data={"photo": (BytesIO(_image_bytes()), "thor.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 502
    payload = response.get_json()
    assert payload["retryable"] is False
    assert payload["code"] == "credencial-recusada"
    # O que o vacinador le nao pode ser o traceback do boto3.
    assert "PutObject" not in payload["message"]
    assert "administrador" in payload["message"]


def test_upload_to_s3_aceita_upload_stream(monkeypatch):
    import app as app_module
    from services.photo_intake import _UploadStream

    captured = {}

    class DummyS3:
        def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None):
            captured["bucket"] = bucket
            captured["key"] = key
            captured["extra"] = ExtraArgs
            captured["data"] = fileobj.read()

    monkeypatch.setattr(app_module, "BUCKET", "test-bucket")
    monkeypatch.setattr(app_module, "_s3", lambda: DummyS3())

    stream = _UploadStream(_image_bytes(), "image/jpeg")
    # Não pode quebrar com AttributeError: '_UploadStream' object has no attribute 'stream'
    url = app_module.upload_to_s3(stream, "animal.jpg", folder="animals")

    assert url == f"https://test-bucket.s3.amazonaws.com/{captured['key']}"
    assert captured["bucket"] == "test-bucket"
    assert captured["key"].startswith("animals/animal.jpg")


def test_endpoint_foto_pmo_com_upload_to_s3_real(app, client, monkeypatch):
    with app.app_context():
        user_id, pmo_animal_id = _setup_animal("s3-real", email="foto-real@example.com")

    import app as app_module

    captured = {}

    class DummyS3:
        def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None):
            captured["bucket"] = bucket
            captured["key"] = key
            captured["extra"] = ExtraArgs

    monkeypatch.setattr(app_module, "BUCKET", "test-bucket")
    monkeypatch.setattr(app_module, "_s3", lambda: DummyS3())

    _pmo_login(client, user_id)
    response = client.post(
        f"/vacina-pmo/animal/{pmo_animal_id}/photo",
        data={"photo": (BytesIO(_image_bytes()), "thor.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["image_url"].startswith("https://test-bucket.s3.amazonaws.com/animals/")


def test_diagnostico_e_so_para_admin(app, client):
    with app.app_context():
        user = User(name="Vacinador", email="vac-diag@example.com", role="vacinador")
        user.set_password("senha")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _pmo_login(client, user_id)
    # 404 e nao 403 de proposito: o tratador de erros do app mascara 403 como
    # 404 nas respostas JSON para nao revelar que o recurso existe. O que
    # importa aqui e que quem nao e admin nao recebe o diagnostico.
    resposta = client.get("/vacina-pmo/diagnostico-foto")
    assert resposta.status_code in (403, 404)
    assert "diagnostico" not in (resposta.get_json() or {})


def test_diagnostico_diz_que_falta_bucket_sem_vazar_credencial(app, client, monkeypatch):
    with app.app_context():
        user = User(name="Admin Diag", email="admin-diag@example.com", role="admin")
        user.set_password("senha")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    monkeypatch.delenv("S3_BUCKET_NAME", raising=False)

    _pmo_login(client, user_id)
    response = client.get("/vacina-pmo/diagnostico-foto")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["diagnostico"]["bucket_configurado"] is False
    # Booleanos, nunca o valor: o diagnostico nao pode virar um vazamento.
    texto = response.get_data(as_text=True)
    for suspeito in ("AWS_SECRET_ACCESS_KEY=", "aws_secret"):
        assert suspeito not in texto


# --- tela -----------------------------------------------------------------


def test_erro_retentavel_para_depois_de_um_numero_de_tentativas(source):
    assert "const PHOTO_MAX_AUTO_ATTEMPTS" in source

    defer = function_body(source, "deferredQueueRecord")
    assert "maxAttempts" in defer
    assert "exhausted: esgotou" in defer
    # Sem o limite, a foto repetia a mesma falha para sempre e nunca chegava
    # ao estado que mostra o motivo.
    assert "attempts >= maxAttempts" in defer

    deferir_foto = function_body(source, "deferQueuedPhoto")
    assert "maxAttempts: PHOTO_MAX_AUTO_ATTEMPTS" in deferir_foto


def test_motivo_acompanha_tambem_o_estado_que_ainda_vai_tentar(source):
    setter = function_body(source, "setAnimalQueuedPhoto")
    assert "['failed', 'error'].includes(uploadState)" in setter, (
        "o estado 'error' tambem precisa carregar o motivo: era ele que ficava mudo"
    )

    queued = function_body(source, "uploadQueuedPhoto")
    assert "photoUploadError = navigator.onLine === false ? '' : motivo" in queued


def test_modal_explica_qualquer_estado_e_nao_so_o_definitivo(source):
    advice = function_body(source, "photoModalAdvice")
    for estado in ("'uploading'", "'pending'", "'error'"):
        assert estado in advice, f"o modal precisa saber explicar {estado}"

    abrir = function_body(source, "openPhotoModal")
    assert "photoModalAdvice(animal)" in abrir
    # O botao de reenviar aparece sempre que ha algo a fazer, nao so em 'failed'.
    assert "aviso.acao" in abrir


def test_estado_que_ainda_tenta_nao_usa_a_mesma_cor_do_que_parou(source):
    # Quando 'error' e 'failed' eram ambos vermelhos, o unico aviso que exigia
    # acao se perdia no meio dos que se resolviam sozinhos.
    error_badge = re.search(
        r'\.pmo-animal-photo-badge\[data-state="error"\] \{ background: (#[0-9a-fA-F]{6}); \}',
        source,
    )
    failed_badge = re.search(
        r'\.pmo-animal-photo-badge\[data-state="failed"\] \{ background: (#[0-9a-fA-F]{6}); \}',
        source,
    )
    assert error_badge and failed_badge
    assert error_badge.group(1).lower() != failed_badge.group(1).lower()


def test_motivo_sobrevive_a_troca_de_status_do_animal(source):
    trecho = function_body(source, "replaceStateRow")
    assert "'photoUploadError'" in trecho, (
        "marcar 'vacinado' logo depois da falha nao pode apagar o motivo"
    )


def test_erro_pode_ser_copiado_para_quem_consegue_resolver(source):
    assert 'id="pmo-photo-copy-error"' in source
    assert "navigator.clipboard.writeText" in source
