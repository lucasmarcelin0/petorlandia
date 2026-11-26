"""Casa a Casa no navegador: a Prefeitura integrada sem sair do mapa.

Regras protegidas:
- o 🏛️ abre a tela de comunicar numa janela por cima do mapa (página embutida, sem cabeçalho do site),
  fecha e volta ao mapa como estava; "Abrir em outra aba" continua disponível;
- abaixo de "Cores", ligar "Aguardando atendimento" põe no mapa as comunicações abertas; tocar numa
  delas mostra o resumo, e "Ver comunicação" abre a comunicação na mesma janela.

Os cabeçalhos de segurança do Flask vão junto com cada resposta: a moldura só funciona se o servidor
permitir. Sem Playwright/Chromium o arquivo é pulado.
"""
from __future__ import annotations

import importlib.util
import mimetypes
from pathlib import Path

from extensions import db

_spec = importlib.util.spec_from_file_location(
    "_casa_a_casa_navegador_pi", Path(__file__).resolve().parent / "test_casa_a_casa_navegador.py")
_nav = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_nav)
navegador = _nav.navegador  # fixtures reaproveitadas
base = _nav.base
_casa = _nav._casa
ORIGEM, TELA, RAIZ = _nav.ORIGEM, _nav.TELA, _nav.RAIZ


def _tratar_com_cabecalhos(client):
    def tratar(route):
        pedido = route.request
        if not pedido.url.startswith(ORIGEM):
            return route.fulfill(status=204, body="")
        caminho = pedido.url.split(ORIGEM, 1)[-1]
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
        cabecalhos = {k: v for k, v in resposta.headers.items()
                      if k.lower() in ("x-frame-options", "content-security-policy", "permissions-policy")}
        if resposta.status_code in (301, 302, 303, 307, 308):
            cabecalhos["Location"] = resposta.headers["Location"]
        return route.fulfill(status=resposta.status_code, body=resposta.get_data(), headers=cabecalhos,
                             content_type=resposta.headers.get("Content-Type", "text/plain"))
    return tratar


def test_comunicar_em_janela_e_camada_no_mapa(navegador, client, base):
    from models.limpeza import LimpezaSolicitacao
    from services import limpeza_urbana as servico_limpeza
    from services.entomologia_service import load_field_territory

    cx, cy = load_field_territory()["features"][0]["properties"]["label"]
    ana = _casa.agente()
    servico_limpeza.conceder(ana, ("equipe",), None, None, "Coordenação")  # comunicar + mapa, papel real
    db.session.add_all([
        LimpezaSolicitacao(numero=7, autor_id=ana.id, categorias="outro", descricao="Entulho na calçada",
                           latitude=cy, longitude=cx, origem_local="gps", foto_url="https://exemplo.test/f.jpg",
                           status="aberta"),
        LimpezaSolicitacao(numero=8, autor_id=ana.id, categorias="outro", descricao="Já limpo",
                           latitude=cy + 0.0004, longitude=cx, origem_local="gps", foto_url="https://exemplo.test/g.jpg",
                           status="concluida"),
    ])
    db.session.commit()
    _casa.entrar(client, ana)

    contexto = navegador.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                                     service_workers="block")
    contexto.add_init_script(
        "localStorage.setItem('cac:prefs:v1', JSON.stringify({modo: 'rua', painel: false, vista: [%r, %r, 17]}))" % (cy, cx))
    contexto.route("**/*", _tratar_com_cabecalhos(client))
    aba = contexto.new_page()
    erros: list[str] = []
    aba.on("pageerror", lambda e: erros.append(str(e)))
    try:
        aba.goto(ORIGEM + TELA)
        aba.locator("#cac-prefeitura").wait_for()

        # 🏛️: a comunicação abre por cima do mapa, sem trocar de página.
        aba.locator("#cac-prefeitura").click()
        janela = aba.locator("#cac-pi-janela")
        janela.wait_for(state="visible")
        assert aba.url == ORIGEM + TELA
        moldura = aba.frame_locator("#cac-pi-moldura")
        moldura.locator("form[data-offline-comunicacao]").wait_for()
        quadro = aba.frame(url=lambda url: "/limpeza-urbana/comunicar" in url)
        assert quadro.evaluate("document.documentElement.classList.contains('limpeza-embutida')")
        assert not quadro.locator("nav.navbar").is_visible()
        assert aba.locator("#cac-pi-aba").get_attribute("target") == "_blank"
        assert aba.locator("#cac-pi-aba").get_attribute("href").endswith("/limpeza-urbana/comunicar")

        aba.locator("#cac-pi-fechar").click()
        janela.wait_for(state="hidden")

        # Camada abaixo de "Cores": só as abertas.
        legenda, camada = aba.locator("#cac-legenda").bounding_box(), aba.locator("#cac-pi").bounding_box()
        assert camada["y"] >= legenda["y"] + legenda["height"] - 1
        aba.locator("#cac-pi summary").click()
        aba.locator("#cac-pi input[data-pi-status='aberta']").check()
        marcas = aba.locator(".cac-pi-marca")
        marcas.first.wait_for()
        assert marcas.count() == 1 and "aberta" in marcas.first.get_attribute("class")
        assert "1 comunicação" in aba.locator("#cac-pi-nota").inner_text()

        aba.locator("#cac-pi input[data-pi-status='concluida']").check()
        aba.wait_for_function("() => document.querySelectorAll('.cac-pi-marca').length === 2")

        # Tocar na marca mostra o resumo, e não a ficha de uma casa embaixo dela.
        aba.locator(".cac-pi-marca.aberta").click()
        balao = aba.locator(".cac-pi-balao")
        balao.wait_for()
        assert "Nº 7" in balao.inner_text() and "Entulho na calçada" in balao.inner_text()
        assert aba.locator("#cac-ficha").is_hidden()
        balao.locator(".cac-pi-abrir").click()
        janela.wait_for(state="visible")
        assert "nº 7" in aba.locator("#cac-pi-titulo").inner_text()
        aba.wait_for_function(
            "() => (document.querySelector('#cac-pi-moldura').contentWindow.location.pathname || '').includes('/limpeza-urbana/solicitacao/')")
        aba.locator("#cac-pi-fechar").click()
        janela.wait_for(state="hidden")

        # Desligar tudo tira a camada do mapa.
        aba.locator("#cac-pi input[data-pi-status='aberta']").uncheck()
        aba.locator("#cac-pi input[data-pi-status='concluida']").uncheck()
        aba.wait_for_function("() => !document.querySelector('.cac-pi-marca')")
        assert not erros, erros
    finally:
        contexto.close()
