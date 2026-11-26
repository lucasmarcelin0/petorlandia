"""Casa a Casa no navegador: o 📍 mostra e acompanha onde a pessoa está.

Roda a tela de verdade (HTML do Flask + static/js) num Chromium com GPS simulado. As chamadas da página
são respondidas pelo cliente de teste do Flask, com a base fictícia de ``test_entomologia_casa_a_casa``.

Regra protegida: tocar no 📍 liga o ponto azul com o círculo da precisão, o ponto acompanha a pessoa
enquanto ela anda e tocar de novo (com o ponto à vista) desliga e apaga o ponto.

Sem Playwright/Chromium o arquivo é pulado.
"""
from __future__ import annotations

import importlib.util
import mimetypes
import os
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
ORIGEM = "https://petorlandia.test"
TELA = "/sfa/entomologia/casa-a-casa"

_spec = importlib.util.spec_from_file_location(
    "_casa_a_casa_base_gps", Path(__file__).resolve().parent / "test_entomologia_casa_a_casa.py")
_casa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_casa)
base = _casa.base  # fixture reaproveitada


@pytest.fixture(scope="module")
def navegador():
    pytest.importorskip("playwright", reason="playwright não instalado")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        caminho = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        try:
            chromium = p.chromium.launch(executable_path=caminho) if caminho else p.chromium.launch()
        except Exception as erro:  # navegador não baixado neste ambiente
            pytest.skip(f"Chromium do Playwright indisponível: {erro}")
        yield chromium
        chromium.close()


def _tratar(client):
    def tratar(route):
        pedido = route.request
        caminho = pedido.url.split(ORIGEM, 1)[-1]
        if not pedido.url.startswith(ORIGEM):
            return route.fulfill(status=204, body="")  # mapas de fundo e afins: fora do teste
        sem_query = caminho.split("?", 1)[0]
        if sem_query.startswith("/static/"):
            arquivo = RAIZ / sem_query.lstrip("/")
            if arquivo.is_file():
                tipo = mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream"
                return route.fulfill(status=200, body=arquivo.read_bytes(), content_type=tipo)
            return route.fulfill(status=404, body="")
        resposta = client.open(caminho, method=pedido.method, data=pedido.post_data_buffer,
                               headers={k: v for k, v in pedido.headers.items() if k.lower() in ("content-type", "accept", "x-csrftoken")},
                               base_url="https://localhost")
        return route.fulfill(status=resposta.status_code, body=resposta.get_data(),
                             content_type=resposta.headers.get("Content-Type", "text/plain"))
    return tratar


def test_botao_gps_liga_acompanha_e_desliga(navegador, client, base):
    _casa.entrar(client, _casa.agente())
    contexto = navegador.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                                     geolocation={"latitude": -20.7205, "longitude": -47.8750, "accuracy": 12},
                                     permissions=["geolocation"], service_workers="block")
    contexto.route("**/*", _tratar(client))
    aba = contexto.new_page()
    erros: list[str] = []
    aba.on("pageerror", lambda e: erros.append(str(e)))
    try:
        aba.goto(ORIGEM + TELA)
        botao = aba.locator("#cac-onde")
        botao.wait_for()
        assert botao.get_attribute("aria-pressed") == "false"

        ponto, precisao = aba.locator("path.cac-eu"), aba.locator("path.cac-eu-precisao")
        assert ponto.count() == 0

        botao.click()
        ponto.wait_for()
        assert precisao.count() == 1 and botao.get_attribute("aria-pressed") == "true"
        # Centraliza no primeiro sinal: o ponto aparece no meio do mapa.
        mapa, caixa = aba.locator("#cac-mapa").bounding_box(), ponto.bounding_box()
        meio_x, meio_y = caixa["x"] + caixa["width"] / 2, caixa["y"] + caixa["height"] / 2
        assert abs(meio_x - (mapa["x"] + mapa["width"] / 2)) < 30
        assert abs(meio_y - (mapa["y"] + mapa["height"] / 2)) < 30

        # A pessoa anda: o ponto vai junto, sem precisar tocar de novo.
        antes = ponto.get_attribute("d")
        contexto.set_geolocation({"latitude": -20.7207, "longitude": -47.8748, "accuracy": 10})
        aba.wait_for_function("antes => document.querySelector('path.cac-eu').getAttribute('d') !== antes", arg=antes)

        botao.click()  # ponto à vista: desliga e apaga
        aba.wait_for_function("() => !document.querySelector('path.cac-eu, path.cac-eu-precisao')")
        assert botao.get_attribute("aria-pressed") == "false"
        assert not erros, erros
    finally:
        contexto.close()


# ---------------------------------------------------------------------------
# Toque no número da casa
# ---------------------------------------------------------------------------
# Regra protegida: no celular, o toque no número abre a ficha daquela casa sempre — com o dedo um pouco
# ao lado, com o dedo tremendo, com o mapa se atualizando durante o toque e no ponto pequeno do zoom
# intermediário. Errar por pouco não pode cair no quarteirão (que reenquadra o mapa no modo Rua).

def _abrir_no_quarteirao(navegador, client, zoom):
    from services.entomologia_service import load_field_territory

    cx, cy = load_field_territory()["features"][0]["properties"]["label"]
    _casa.entrar(client, _casa.agente())
    contexto = navegador.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                                     service_workers="block")
    contexto.add_init_script(
        "localStorage.setItem('cac:prefs:v1', JSON.stringify({modo: 'rua', painel: false, vista: [%r, %r, %r]}))"
        % (cy, cx, zoom))
    contexto.route("**/*", _tratar(client))
    aba = contexto.new_page()
    erros: list[str] = []
    aba.on("pageerror", lambda e: erros.append(str(e)))
    aba.goto(ORIGEM + TELA)
    return contexto, aba, erros


def _toque(aba, x, y, tremor=0):
    """Dedo de verdade (eventos de toque do Chromium): encosta, treme ``tremor`` px e solta."""
    cdp = aba.context.new_cdp_session(aba)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    for passo in range(1, 4) if tremor else ():
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x + tremor * passo / 3, "y": y + tremor * passo / 3}]})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    cdp.detach()


def _ficha_aberta(aba):
    aba.locator("#cac-ficha:not([hidden])").wait_for(timeout=4000)
    return aba.locator("#cac-ficha-titulo").inner_text()


def test_toque_no_numero_abre_a_casa_mesmo_com_dedo_ao_lado_ou_tremendo(navegador, client, base):
    contexto, aba, erros = _abrir_no_quarteirao(navegador, client, 19.5)
    try:
        numero = aba.locator(".cac-casa span", has_text="10").first
        numero.wait_for()
        caixa = numero.bounding_box()
        meio_x, meio_y = caixa["x"] + caixa["width"] / 2, caixa["y"] + caixa["height"] / 2

        # Dedo trêmulo (8 px): o Leaflet já trata como arrasto; o toque precisa continuar valendo.
        _toque(aba, meio_x, meio_y, tremor=8)
        assert _ficha_aberta(aba) == "Rua Um, 10"
        aba.locator("#cac-ficha-fechar").click()
        aba.locator("#cac-ficha").wait_for(state="hidden")

        # Arrasto de verdade continua sendo arrasto: não abre casa nenhuma.
        _toque(aba, meio_x, meio_y + 120, tremor=60)
        aba.wait_for_timeout(500)
        assert aba.locator("#cac-ficha").is_hidden()
        assert not erros, erros
    finally:
        contexto.close()


def test_toque_perto_do_ponto_abre_a_casa_no_zoom_intermediario(navegador, client, base):
    contexto, aba, erros = _abrir_no_quarteirao(navegador, client, 17)
    try:
        aba.wait_for_function("() => document.getElementById('cac-dica').textContent.includes('ponto da casa')")
        mapa = aba.locator("#cac-mapa").bounding_box()
        # As casas fictícias ficam a poucos metros do centro do quarteirão, que está no meio do mapa.
        # Tocar 12 px ao lado do meio: antes caía no quarteirão, que no modo Rua reenquadra o mapa e muda os
        # números de lugar (o "às vezes não funciona" do campo); agora abre a casa mais próxima.
        _toque(aba, mapa["x"] + mapa["width"] / 2 + 12, mapa["y"] + mapa["height"] / 2)
        assert _ficha_aberta(aba).startswith("Rua ")
        assert not erros, erros
    finally:
        contexto.close()


def test_toque_no_numero_sobrevive_a_atualizacao_da_equipe_no_meio_do_toque(navegador, client, base):
    """Outro agente registra e a página busca a novidade com o dedo encostado: o toque ainda vale e o mapa
    só é redesenhado depois que o dedo sai (os números não trocam de lugar debaixo dele)."""
    contexto, aba, erros = _abrir_no_quarteirao(navegador, client, 19.5)
    try:
        numero = aba.locator(".cac-casa span", has_text="10").first
        numero.wait_for()
        caixa = numero.bounding_box()
        x, y = caixa["x"] + caixa["width"] / 2, caixa["y"] + caixa["height"] / 2
        cdp = aba.context.new_cdp_session(aba)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        # Enquanto o dedo está na tela, chega a visita de outra casa e a página busca a novidade.
        assert _casa.enviar(client, _casa.visita(base["a"], imovel="1002", uuid="visita-equipe-1")).status_code == 200
        aba.evaluate("() => window.dispatchEvent(new Event('online'))")
        aba.wait_for_timeout(700)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        cdp.detach()
        assert _ficha_aberta(aba) == "Rua Um, 10"
        # Solto o dedo, o mapa mostra a casa que a equipe registrou.
        aba.wait_for_function("() => document.querySelectorAll('.cac-casa').length >= 4")
        assert not erros, erros
    finally:
        contexto.close()
