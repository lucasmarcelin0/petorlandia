"""Prefeitura integrada no navegador: quem comunica sempre recebe um retorno claro.

Roda a tela "Comunicar" de verdade (HTML do Flask + static/js) num Chromium com GPS
simulado. O servidor é simulado pela própria página de teste (``page.route``), para
cobrir com precisão o que acontece na rua: vários envios seguidos, servidor que
recusa, conexão que cai e envio novo enquanto o anterior ainda sobe.

Regra que estes testes protegem: depois de tocar em "Enviar comunicação", aparece
sempre um pop-up — parabéns, "guardada no celular" ou "falta um detalhe" — e
nunca uma tela parada sem resposta.

Sem Playwright/Chromium o arquivo é pulado. Para apontar um Chromium instalado à
parte, use PLAYWRIGHT_CHROMIUM_EXECUTABLE.
"""
from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
from pathlib import Path

import pytest

from models import User

RAIZ = Path(__file__).resolve().parents[1]
ORIGEM = "https://petorlandia.test"
PONTO = {"latitude": -20.7205, "longitude": -47.8750, "accuracy": 8}

_spec_base = None


def _base():
    global _spec_base
    if _spec_base is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_limpeza_base_navegador", Path(__file__).resolve().parent / "test_limpeza_urbana.py")
        _spec_base = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_spec_base)
    return _spec_base


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
def html_comunicar(client):
    """HTML real da tela, renderizado pelo Flask para um colaborador."""
    base = _base()
    morador = User(name="Morador", email="morador@example.test", password_hash="x", role="adotante")
    from extensions import db

    db.session.add(morador)
    db.session.commit()
    base.dar(morador, "colaborador")
    base.entrar(client, morador)
    resposta = client.get("/limpeza-urbana/comunicar")
    assert resposta.status_code == 200
    return resposta.get_data(as_text=True)


class Servidor:
    """Respostas do servidor simuladas; ``modo`` decide o que cada envio recebe."""

    def __init__(self, html):
        self.html = html
        self.modo = "ok"          # ok | recusa | queda | pendurado
        self.atraso = 0.0         # segundos de espera em cada envio (rede lenta)
        self.recebidas = 0
        self._trava = threading.Lock()

    def tratar(self, route):
        pedido = route.request
        caminho = pedido.url.split(ORIGEM, 1)[-1].split("?", 1)[0]
        if caminho.startswith("/static/"):
            arquivo = RAIZ / caminho.lstrip("/")
            if arquivo.is_file():
                tipo = mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream"
                return route.fulfill(status=200, body=arquivo.read_bytes(), content_type=tipo)
            return route.fulfill(status=404, body="")
        if caminho == "/limpeza-urbana/comunicar" and self.modo == "pendurado":
            return None  # sinal fraco: o celular diz que tem internet, mas nada responde
        if caminho == "/limpeza-urbana/comunicar" and pedido.method == "GET":
            return route.fulfill(status=200, body=self.html, content_type="text/html; charset=utf-8")
        if caminho == "/limpeza-urbana/comunicar" and pedido.method == "POST":
            if self.atraso:
                time.sleep(self.atraso)
            if self.modo == "queda":
                return route.abort("internetdisconnected")
            if self.modo == "recusa":
                return route.fulfill(status=400, content_type="application/json", body=json.dumps(
                    {"erro": "Não recebemos a localização. Permita o acesso à localização e tire a foto no local."}))
            with self._trava:
                self.recebidas += 1
                numero = self.recebidas
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "destino": "/limpeza-urbana/minhas", "id": numero, "numero": numero,
                "parabens": {"tipo": "comunicacao", "numero": numero, "total": numero, "emoji": "🌱",
                             "nivel": "Olho vivo", "frase": "Sua primeira comunicação!", "novo_nivel": numero == 1,
                             "proximo_nivel": "Vizinho atento", "faltam": max(0, 3 - numero), "progresso": 50},
            }))
        # Demais chamadas do layout (avisos, notificações…): resposta vazia em JSON.
        return route.fulfill(status=200, content_type="application/json", body="{}")


@pytest.fixture
def tela(navegador, html_comunicar, tmp_path):
    from PIL import Image

    foto = tmp_path / "foto.jpg"
    Image.new("RGB", (64, 48), (120, 160, 90)).save(foto, format="JPEG")
    servidor = Servidor(html_comunicar)
    contexto = navegador.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                                     geolocation=PONTO, permissions=["geolocation"],
                                     service_workers="block")
    contexto.route("**/*", servidor.tratar)
    aba = contexto.new_page()
    erros: list[str] = []
    aba.on("pageerror", lambda e: erros.append(str(e)))
    aba.goto(ORIGEM + "/limpeza-urbana/comunicar")
    aba.wait_for_function("window.limpezaParabens && document.querySelector('[data-offline-comunicacao]')")
    aba.wait_for_timeout(800)  # GPS ligado e armazenamento do aparelho aberto
    yield aba, servidor, foto, contexto
    assert erros == []
    contexto.close()


def _preencher(aba, foto):
    aba.check("input[name=categoria][value=lixo]")
    aba.set_input_files("input[type=file][name=foto][data-limpeza-arquivo=camera]", str(foto))
    aba.wait_for_timeout(300)


def _enviar_e_esperar_popup(aba, limite_ms=8000):
    inicio = time.monotonic()
    aba.click("form[data-offline-comunicacao] button[type=submit]")
    aba.wait_for_selector("#limpeza-parabens:not([hidden])", timeout=limite_ms)
    return (time.monotonic() - inicio) * 1000, aba.text_content("#lp-titulo"), aba.text_content(".lp-sub")


def _fechar_popup(aba):
    aba.keyboard.press("Escape")
    aba.wait_for_selector("#limpeza-parabens", state="hidden")


def test_varios_envios_seguidos_mostram_parabens_em_todos(tela):
    aba, servidor, foto, _ = tela
    for numero in range(1, 5):
        _preencher(aba, foto)
        ms, titulo, sub = _enviar_e_esperar_popup(aba)
        assert titulo == "Parabéns, deu certo!", numero
        assert sub == f"Comunicação nº {numero} enviada"
        # Antes, a partir do 2º envio a tela esperava até 15 s por uma leitura nova do GPS.
        assert ms < 6000, f"envio {numero} levou {ms:.0f} ms"
        aba.click(".lp-acoes button.btn-success")  # "Comunicar outro problema"
        aba.wait_for_selector("#limpeza-parabens", state="hidden")
    assert servidor.recebidas == 4
    # Nada ficou guardado no aparelho e a caixa de pendências some.
    assert aba.eval_on_selector("#limpeza-pendencias", "e => e.classList.contains('d-none')")


def test_botao_mostra_o_andamento_enquanto_envia(tela):
    aba, servidor, foto, _ = tela
    servidor.atraso = 1.5
    _preencher(aba, foto)
    aba.click("form[data-offline-comunicacao] button[type=submit]")
    aba.wait_for_function("document.querySelector('form[data-offline-comunicacao] button[type=submit]').disabled")
    texto = aba.text_content("form[data-offline-comunicacao] button[type=submit]")
    assert "Registrando a localização" in texto or "Enviando" in texto
    aba.wait_for_selector("#limpeza-parabens:not([hidden])", timeout=10000)
    assert aba.text_content("form[data-offline-comunicacao] button[type=submit]").strip() == "Enviar comunicação"


def test_recusa_do_servidor_aparece_na_frente_com_caminho_para_corrigir(tela):
    aba, servidor, foto, _ = tela
    servidor.modo = "recusa"
    _preencher(aba, foto)
    _, titulo, _ = _enviar_e_esperar_popup(aba)
    assert titulo == "Falta um detalhe"
    assert "localização" in aba.text_content("#lp-texto")
    assert aba.is_visible("text=Corrigir agora")
    aba.click("text=Corrigir agora")
    aba.wait_for_selector("#limpeza-parabens", state="hidden")
    # A pendência é carregada do armazenamento do aparelho (assíncrono).
    aba.wait_for_function("document.getElementById('limpeza-pendencias').textContent.includes('Motivo da recusa')",
                          timeout=5000)
    assert "Motivo da recusa" in aba.text_content("#limpeza-pendencias")


def test_conexao_que_cai_avisa_que_ficou_guardada_e_envia_depois(tela):
    aba, servidor, foto, _ = tela
    servidor.modo = "queda"
    _preencher(aba, foto)
    _, titulo, _ = _enviar_e_esperar_popup(aba)
    assert titulo == "Comunicação guardada!"
    _fechar_popup(aba)
    # A conexão volta: "Enviar pendentes" manda e comemora.
    servidor.modo = "ok"
    aba.click("#limpeza-sincronizar")
    aba.wait_for_selector("#limpeza-parabens:not([hidden])", timeout=8000)
    assert aba.text_content("#lp-titulo") == "Parabéns, deu certo!"
    assert servidor.recebidas == 1


def test_sem_internet_avisa_que_ficou_guardada(tela):
    aba, servidor, foto, contexto = tela
    contexto.set_offline(True)
    _preencher(aba, foto)
    _, titulo, _ = _enviar_e_esperar_popup(aba)
    assert titulo == "Comunicação guardada!"
    assert servidor.recebidas == 0
    _fechar_popup(aba)
    contexto.set_offline(False)  # evento "online": envia sozinha e comemora
    aba.wait_for_selector("#limpeza-parabens:not([hidden])", timeout=8000)
    assert aba.text_content("#lp-titulo") == "Parabéns, deu certo!"
    assert servidor.recebidas == 1


def test_envio_novo_durante_outro_ainda_recebe_resposta(tela):
    aba, servidor, foto, _ = tela
    servidor.atraso = 2.0  # rede lenta: o 1º envio ainda está subindo
    _preencher(aba, foto)
    aba.click("form[data-offline-comunicacao] button[type=submit]")
    # Enquanto o 1º sobe, a pessoa (em outra aba da mesma tela) dispara um envio:
    aba.evaluate("document.getElementById('limpeza-sincronizar').click()")
    aba.wait_for_selector("#limpeza-parabens:not([hidden])", timeout=15000)
    assert aba.text_content("#lp-titulo") == "Parabéns, deu certo!"
    aba.wait_for_timeout(2500)
    assert servidor.recebidas == 1  # um envio por vez, sem duplicar


def test_sinal_fraco_responde_em_ate_10_segundos_e_segue_enviando(tela):
    aba, servidor, foto, _ = tela
    servidor.modo = "pendurado"
    _preencher(aba, foto)
    ms, titulo, sub = _enviar_e_esperar_popup(aba, limite_ms=14000)
    # Antes, o botão ficava 20 s ou mais em "Enviando…" sem nenhum retorno.
    assert titulo == "Comunicação guardada!"
    assert "lenta" in sub
    assert ms < 12500, f"retorno levou {ms:.0f} ms"
    assert aba.text_content("form[data-offline-comunicacao] button[type=submit]").strip() == "Enviar comunicação"
    # A conexão melhora: a pendência sai sozinha e o pop-up vira parabéns.
    servidor.modo = "ok"
    _fechar_popup(aba)
    aba.click("#limpeza-sincronizar")
    aba.wait_for_selector("#limpeza-parabens:not([hidden])", timeout=30000)
    assert aba.text_content("#lp-titulo") == "Parabéns, deu certo!"
    assert servidor.recebidas == 1
