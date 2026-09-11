# -*- coding: utf-8 -*-
"""A foto sobe leve e o navegador nao rebaixa a mesma imagem duas vezes.

Relato de campo (11/09/2026): erros de envio frequentes e sem explicacao. Duas
causas de desempenho estavam por tras da maioria deles:

1. so era reduzida a foto acima de 2,5 MB -- e quase toda foto de celular cabe
   abaixo disso. Ela subia em resolucao cheia pelo dado movel do interior, o
   que estourava o tempo limite de envio e voltava para a fila de retentativa;
2. a foto servida pelo proxy (`/photo-src`, usada na carteirinha e no video)
   era rebaixada do S3 pelo dyno a cada render: o `after_request` sobrescrevia
   o `Cache-Control` da view com `no-store`.

Estes testes travam as duas correcoes.
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from extensions import db
from models import Animal, PmoVaccinationVisit, User
from services.photo_intake import (
    CONVERSION_MAX_SIDE,
    RECOMPRESS_ABOVE_BYTES,
    normalize_photo_upload,
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


def _foto(largura=4032, altura=3024, formato="JPEG", qualidade=95):
    """Imagem com ruido, para o JPEG nao comprimir a quase nada."""
    import random

    random.seed(7)
    imagem = Image.new("RGB", (largura, altura))
    imagem.putdata([
        (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        for _ in range(largura * altura)
    ])
    buffer = BytesIO()
    if formato == "JPEG":
        imagem.save(buffer, format=formato, quality=qualidade)
    else:
        imagem.save(buffer, format=formato)
    return buffer.getvalue()


# --- servidor: a foto guardada tem o tamanho que o site usa ----------------


def test_foto_de_celular_e_reduzida_antes_de_ir_para_o_s3():
    original = _foto()
    assert len(original) > RECOMPRESS_ABOVE_BYTES, "fixture precisa ser uma foto grande"

    foto = normalize_photo_upload(original)

    assert foto.converted is True
    guardada = foto.stream.getvalue()
    assert len(guardada) < len(original)
    with Image.open(BytesIO(guardada)) as imagem:
        assert max(imagem.size) <= CONVERSION_MAX_SIDE


def test_foto_ja_no_tamanho_certo_passa_intacta():
    original = _foto(largura=1200, altura=900, qualidade=70)
    assert len(original) <= RECOMPRESS_ABOVE_BYTES

    foto = normalize_photo_upload(original)

    assert foto.converted is False
    assert foto.stream.getvalue() == original


def test_reducao_nunca_devolve_arquivo_maior():
    # PNG pequeno de traco: reencodar para JPEG engordaria o arquivo.
    buffer = BytesIO()
    Image.new("RGB", (2000, 40), color=(255, 255, 255)).save(buffer, format="PNG")
    original = buffer.getvalue()

    foto = normalize_photo_upload(original)

    assert len(foto.stream.getvalue()) <= len(original)


def test_png_transparente_nao_vira_foto_preta():
    buffer = BytesIO()
    Image.new("RGBA", (2400, 1800), (255, 0, 0, 0)).save(buffer, format="PNG")

    foto = normalize_photo_upload(buffer.getvalue())

    with Image.open(foto.stream) as imagem:
        # Transparente vira branco, nao preto.
        assert imagem.convert("RGB").getpixel((5, 5)) == (255, 255, 255)


# --- proxy da foto: cache e 304 -------------------------------------------


def _pmo_login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _visita_com_foto(sheet_gid, email):
    user = User(name="Vacinador Perf", email=email, role="vacinador")
    user.set_password("senha")
    db.session.add(user)
    persist_vacina_pmo_rows(
        [{
            "id": "sheet-1",
            "status": "pendente",
            "tutor": "Tutor Perf",
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
        }],
        spreadsheet_id="sheet-test",
        sheet_gid=sheet_gid,
        sheet_title="18/06/2026",
    )
    db.session.commit()
    visita = PmoVaccinationVisit.query.filter_by(sheet_gid=sheet_gid).one()
    pmo_animal = visita.animals[0]
    animal = Animal(name="Lua", user_id=user.id, image="https://bucket.example/animals/lua.jpg")
    db.session.add(animal)
    db.session.flush()
    pmo_animal.animal_id = animal.id
    db.session.commit()
    return user.id, pmo_animal.id


def test_foto_do_proxy_pode_ser_cacheada_pelo_navegador(app, client, monkeypatch):
    with app.app_context():
        user_id, pmo_animal_id = _visita_com_foto("perf-cache", "perf-cache@example.com")

    _pmo_login(client, user_id)
    buscas = {"n": 0}

    class _Resposta:
        headers = {"Content-Type": "image/jpeg"}
        content = _foto(largura=64, altura=48)

        def raise_for_status(self):
            return None

    def _fake_fetch(*_args, **_kwargs):
        buscas["n"] += 1
        return _Resposta()

    monkeypatch.setattr("security.url_safe.safe_fetch_url", _fake_fetch)

    primeira = client.get(f"/vacina-pmo/animal/{pmo_animal_id}/photo-src")

    assert primeira.status_code == 200
    # O after_request nao pode transformar isto em `no-store`.
    assert "max-age=3600" in primeira.headers["Cache-Control"]
    assert "private" in primeira.headers["Cache-Control"]
    etag = primeira.headers["ETag"]
    assert etag

    segunda = client.get(
        f"/vacina-pmo/animal/{pmo_animal_id}/photo-src",
        headers={"If-None-Match": etag},
    )

    assert segunda.status_code == 304
    # O 304 sai antes de ir ao S3: o dyno nao rebaixa a imagem de novo.
    assert buscas["n"] == 1


def test_demais_paginas_autenticadas_seguem_sem_cache(app, client):
    with app.app_context():
        user = User(name="Vacinador NoStore", email="perf-nostore@example.com", role="vacinador")
        user.set_password("senha")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _pmo_login(client, user_id)
    resposta = client.get("/vacina-pmo")

    assert resposta.status_code == 200
    assert resposta.headers["Cache-Control"] == "private, no-store"


# --- tela: o aparelho sobe pouco byte -------------------------------------


def test_tela_reduz_toda_foto_e_nao_so_as_gigantes(source):
    corpo = function_body(source, "prepareAnimalPhoto")

    assert "PHOTO_RAW_LIMIT" in corpo
    assert "2.5 * 1024 * 1024" not in corpo, "o corte antigo deixava passar foto de 12 MP"
    assert "const PHOTO_MAX_SIDE = 1600;" in source
    assert "blob.size >= file.size" in corpo, "nunca enviar mais bytes do que o original"
