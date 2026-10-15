# -*- coding: utf-8 -*-
"""Foto do iPhone que chegava sem arquivo ao servidor (15/10/2026).

Em campo, o celular da estagiária (iPhone, iOS 18.7) mostrava "Esta foto não
pode ser enviada assim. Nenhuma foto enviada." com a miniatura quebrada, e o
log de produção tinha `POST .../photo 400 70` (a resposta "Nenhuma foto
enviada"), enquanto o Android do coordenador recebia 200.

Causa: a fila local guardava o `File` cru no IndexedDB. No iOS isso é só uma
referência ao arquivo temporário da câmera/galeria; quando o sistema o limpa, a
foto volta vazia e o formulário sai sem arquivo.

Correção (somente aditiva):
- a fila guarda os bytes em memória, lidos na captura (registros antigos, com
  `file`, continuam funcionando);
- o envio sempre leva nome de arquivo e o servidor não recusa foto boa só por
  vir sem nome;
- a falha diz "ilegível" e manda tirar outra, em vez de prometer reenvio;
- a miniatura local não usa `loading="lazy"` (no iOS ela só carregava depois de
  um toque em outra área da tela).
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import pytest

from tests.test_pmo_foto_falha_visivel import _image_bytes, _pmo_login, _setup_animal


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


# --- servidor ---------------------------------------------------------------


def test_foto_sem_nome_de_arquivo_nao_e_recusada(app, client, monkeypatch):
    with app.app_context():
        user_id, pmo_animal_id = _setup_animal("foto-sem-nome", email="foto-sem-nome@example.com")

    guardados = []
    monkeypatch.setattr(
        "services.photo_storage.store_photo",
        lambda stream, filename, folder="animals", uploader=None: guardados.append(filename)
        or "https://exemplo.test/foto.jpg",
    )

    _pmo_login(client, user_id)
    response = client.post(
        f"/vacina-pmo/animal/{pmo_animal_id}/photo",
        data={"photo": (BytesIO(_image_bytes()), "")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["success"] is True
    assert guardados and guardados[0].endswith(".jpg")


def test_envio_sem_arquivo_explica_e_nao_manda_repetir(app, client):
    with app.app_context():
        user_id, pmo_animal_id = _setup_animal("foto-sem-arquivo", email="foto-sem-arquivo@example.com")

    _pmo_login(client, user_id)
    response = client.post(
        f"/vacina-pmo/animal/{pmo_animal_id}/photo",
        data={},
        content_type="multipart/form-data",
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["retryable"] is False
    assert payload["code"] == "no_file"
    assert "Tirar outra" in payload["message"]


def test_foto_vazia_tem_codigo_proprio(app, client):
    with app.app_context():
        user_id, pmo_animal_id = _setup_animal("foto-vazia", email="foto-vazia@example.com")

    _pmo_login(client, user_id)
    response = client.post(
        f"/vacina-pmo/animal/{pmo_animal_id}/photo",
        data={"photo": (BytesIO(b""), "foto.jpg")},
        content_type="multipart/form-data",
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["retryable"] is False
    assert payload["code"] == "empty_file"


# --- tela -------------------------------------------------------------------


def test_fila_guarda_bytes_e_nao_o_arquivo_cru(source):
    body = function_body(source, "queueAnimalPhotoUpload")
    assert "bytesOfPhoto(file)" in body
    assert "buffer," in body
    # O File cru e justamente o que o iOS invalida dentro do IndexedDB.
    record = body[body.index("const record = {"):body.index("await saveQueuedPhoto(record)")]
    assert "\n      file," not in record


def test_registro_antigo_com_file_continua_valendo(source):
    body = function_body(source, "queuedPhotoFile")
    assert "record.buffer" in body
    assert "return record.file || null" in body
    # Quem le a fila passa pelo helper, nao por `record.file`.
    assert "record.file" not in function_body(source, "uploadQueuedPhoto")
    assert "record.file" not in function_body(source, "setAnimalQueuedPhoto")


def test_envio_sempre_leva_nome_de_arquivo(source):
    body = function_body(source, "uploadAnimalPhoto")
    assert "formData.append('photo', file, file.name || 'foto.jpg')" in body
    assert "unreadablePhotoError()" in body
    assert "'no_file', 'empty_file'" in body


def test_foto_ilegivel_nao_promete_reenvio(source):
    body = function_body(source, "photoModalAdvice")
    assert "photoUploadCode === 'unreadable'" in body
    assert "tentar: false" in body
    assert "aviso.tentar !== false" in source


def test_miniatura_local_nao_usa_lazy(source):
    body = function_body(source, "renderAnimalPhotoControl")
    assert "startsWith('blob:')" in body
    assert 'loading="lazy"' in body  # fotos remotas continuam lazy


def test_escolher_foto_da_retorno_imediato(source):
    assert "showPhotoPreparing(animal);" in function_body(source, "queueAnimalPhotoUpload")
    assert "is-busy" in function_body(source, "showPhotoPreparing")
