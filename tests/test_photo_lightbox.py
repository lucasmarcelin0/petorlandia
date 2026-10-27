"""Tocar numa foto abre ela grande — em qualquer página (static/js/photo_lightbox.js).

Roda o componente de verdade num Chromium. Cobre o que precisa ampliar e,
principalmente, o que NÃO pode ampliar: foto dentro de link continua
navegando, editor de recorte continua arrastando, ícones e imagens
decorativas ficam quietos e quem já trata o clique (preventDefault) manda.

Sem Playwright/Chromium o arquivo é pulado. Para apontar um Chromium
instalado à parte, use PLAYWRIGHT_CHROMIUM_EXECUTABLE.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC = PROJECT_ROOT / "static"
LAYOUT = PROJECT_ROOT / "templates" / "layout.html"

PAGINA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<link rel="stylesheet" href="{bootstrap}">
<link rel="stylesheet" href="{estilos}"></head>
<body>
<header><img id="logo" src="{grande}" alt="PetOrlândia" width="120" height="120"></header>
<main id="main-content">
  <img id="foto" src="{grande}" alt="Foto de Pretinho" width="160" height="160">
  <img id="generica" src="{grande}" alt="Imagem" width="160" height="160">
  <a id="link" href="#destino"><img id="foto-link" src="{grande}" alt="Foto no link" width="160" height="160"></a>
  <img id="decorativa" src="{grande}" alt="" width="160" height="160">
  <img id="icone" src="{pequena}" alt="Ícone" width="24" height="24">
  <div class="photo-cropper"><img id="editor" src="{grande}" alt="Imagem" width="160" height="160"></div>
  <div id="com-acao"><img id="foto-acao" src="{grande}" alt="Foto com ação" width="160" height="160"></div>
  <img id="miniatura" src="{grande}" data-zoom-src="{outra}" alt="Miniatura" width="160" height="160">
  <img id="excluida" src="{grande}" data-no-zoom alt="Não ampliar" width="160" height="160">
  <div id="destino">destino</div>
</main>
<script>
  window.acoes = 0;
  document.getElementById('com-acao').addEventListener('click', (e) => {{
    e.preventDefault(); window.acoes += 1;
  }});
</script>
<script src="{componente}" defer></script>
</body></html>
"""


def _png(destino: Path, lado: int, cor) -> Path:
    from PIL import Image

    Image.new("RGB", (lado, lado), cor).save(destino, format="PNG")
    return destino


def _abrir_navegador(p):
    caminho = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    return p.chromium.launch(executable_path=caminho) if caminho else p.chromium.launch()


@pytest.fixture(scope="module")
def navegador():
    pytest.importorskip("playwright", reason="playwright não instalado")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            chromium = _abrir_navegador(p)
        except Exception as erro:  # navegador não baixado neste ambiente
            pytest.skip(f"Chromium do Playwright indisponível: {erro}")
        yield chromium
        chromium.close()


@pytest.fixture
def pagina(navegador, tmp_path):
    grande = _png(tmp_path / "foto.png", 400, (30, 120, 90))
    outra = _png(tmp_path / "foto-grande.png", 800, (200, 80, 40))
    pequena = _png(tmp_path / "icone.png", 24, (0, 0, 0))
    destino = tmp_path / "pagina.html"
    destino.write_text(
        PAGINA.format(
            bootstrap=(STATIC / "bootstrap.min.css").as_uri(),
            estilos=(STATIC / "styles.css").as_uri(),
            componente=(STATIC / "js" / "photo_lightbox.js").as_uri(),
            grande=grande.as_uri(),
            outra=outra.as_uri(),
            pequena=pequena.as_uri(),
        ),
        encoding="utf-8",
    )
    aba = navegador.new_page(viewport={"width": 390, "height": 844})
    erros: list[str] = []
    aba.on("pageerror", lambda e: erros.append(str(e)))
    aba.goto(destino.as_uri())
    aba.wait_for_function("window.PhotoLightbox && document.getElementById('foto').classList.contains('photo-zoomable')")
    yield aba
    assert erros == []
    aba.close()


def _aberto(aba) -> bool:
    return aba.evaluate("!!document.querySelector('.photo-lightbox.is-open')")


def _src_ampliada(aba) -> str:
    return aba.eval_on_selector(".photo-lightbox__img", "el => el.getAttribute('src') || ''")


def test_layout_carrega_o_visualizador_em_todas_as_paginas():
    html = LAYOUT.read_text(encoding="utf-8")
    assert "js/photo_lightbox.js" in html


def test_tocar_na_foto_amplia_com_legenda_e_fecha(pagina):
    pagina.click("#foto")
    assert _aberto(pagina)
    assert _src_ampliada(pagina).endswith("foto.png")
    assert pagina.inner_text(".photo-lightbox__caption") == "Foto de Pretinho"
    assert pagina.evaluate("document.documentElement.classList.contains('photo-lightbox-aberto')")

    pagina.keyboard.press("Escape")
    assert not _aberto(pagina)
    assert not pagina.evaluate("document.documentElement.classList.contains('photo-lightbox-aberto')")
    # O foco volta para a foto, para quem navega pelo teclado.
    assert pagina.evaluate("document.activeElement.id") == "foto"


def test_fecha_no_botao_e_tocando_fora_da_foto(pagina):
    pagina.click("#foto")
    pagina.click(".photo-lightbox__close")
    assert not _aberto(pagina)

    pagina.click("#foto")
    pagina.mouse.click(5, 5)  # fundo escuro
    assert not _aberto(pagina)


def test_legenda_generica_nao_aparece(pagina):
    pagina.click("#generica")
    assert _aberto(pagina)
    assert pagina.is_hidden(".photo-lightbox__caption")


def test_data_zoom_src_mostra_a_versao_grande(pagina):
    pagina.click("#miniatura")
    assert _src_ampliada(pagina).endswith("foto-grande.png")


def test_teclado_enter_amplia(pagina):
    pagina.focus("#foto")
    pagina.keyboard.press("Enter")
    assert _aberto(pagina)


@pytest.mark.parametrize("alvo", ["#decorativa", "#icone", "#editor", "#excluida", "#logo"])
def test_o_que_nao_e_foto_de_conteudo_nao_amplia(pagina, alvo):
    pagina.click(alvo, force=True)
    assert not _aberto(pagina)
    assert not pagina.eval_on_selector(alvo, "el => el.classList.contains('photo-zoomable')")


def test_foto_dentro_de_link_continua_navegando(pagina):
    pagina.click("#foto-link")
    assert not _aberto(pagina)
    assert pagina.evaluate("location.hash") == "#destino"


def test_quem_ja_trata_o_clique_tem_prioridade(pagina):
    pagina.click("#foto-acao")
    assert not _aberto(pagina)
    assert pagina.evaluate("window.acoes") == 1


def test_foto_que_chega_depois_tambem_amplia(pagina):
    pagina.evaluate(
        """() => {
            const img = document.createElement('img');
            img.id = 'nova';
            img.alt = 'Foto nova';
            img.width = 160; img.height = 160;
            img.src = document.getElementById('foto').src;
            document.querySelector('main').appendChild(img);
        }"""
    )
    pagina.wait_for_function("document.getElementById('nova').classList.contains('photo-zoomable')")
    pagina.click("#nova")
    assert _aberto(pagina)
