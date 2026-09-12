# -*- coding: utf-8 -*-
"""A porta da pagina secreta de jogos, escondida no rodape.

O acesso a /surpresa era um link de patinha sempre visivel no rodape. Ele sumiu
no redesenho do rodape (680c40b, "fix(ui): melhora acessibilidade do logo e
footer em layout"): a rota continuou de pe, mas nao havia mais como chegar nela
sem digitar a URL.

Voltou escondido, por pedido: clicar no "© 2026 PetOrlandia." revela a patinha.

O que estes testes travam:

- a rota /surpresa continua servindo a pagina;
- o rodape tem o gatilho e o link, e o link comeca escondido (um segredo que
  aparece sozinho nao e segredo);
- o gatilho e um <button> com `aria-expanded`, e nao um <span> com onclick --
  esconder o segredo nao pode custar a navegacao por teclado de quem nunca vai
  procura-lo;
- o script e o estilo estao carregados, com versao propria de cache. Sem subir
  a versao do CSS, o gatilho chegaria ao visitante parecendo um botao.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import app  # noqa: F401 - garante que create_app resolva a instancia


RAIZ = Path(__file__).resolve().parents[1]
LAYOUT = RAIZ / "templates" / "layout.html"
SCRIPT = RAIZ / "static" / "js" / "footer_egg.js"
ESTILO = RAIZ / "static" / "css" / "tutor-experience.css"


@pytest.fixture(scope="module")
def layout():
    return LAYOUT.read_text(encoding="utf-8")


# --- a rota ---------------------------------------------------------------


def test_pagina_secreta_continua_de_pe(client):
    resposta = client.get("/surpresa")

    assert resposta.status_code == 200
    # A pagina muda com frequencia: o cache padrao de 7 dias prenderia
    # visitantes em versoes antigas.
    assert resposta.headers.get("Cache-Control") == "no-cache"


# --- o rodape -------------------------------------------------------------


def test_rodape_tem_a_porta_do_easter_egg(layout):
    assert 'id="footer-egg-key"' in layout
    assert 'id="footer-egg-link"' in layout
    assert "url_for('secret_game')" in layout


def test_link_comeca_escondido(layout):
    """Um segredo que aparece sozinho deixa de ser segredo."""
    link = re.search(r'<a[^>]*id="footer-egg-link"[^>]*>', layout, re.S)
    assert link, "o link da patinha nao foi encontrado"
    assert "hidden" in link.group(0)


def test_gatilho_e_um_botao_de_verdade(layout):
    """<span> com onclick nao recebe foco nem e anunciado como acionavel."""
    gatilho = re.search(r'<button[^>]*id="footer-egg-key"[^>]*>', layout, re.S)
    assert gatilho, "o gatilho precisa ser um <button>"
    assert 'type="button"' in gatilho.group(0)
    assert 'aria-expanded="false"' in gatilho.group(0)
    assert 'aria-controls="footer-egg-link"' in gatilho.group(0)


def test_patinha_tem_nome_para_quem_nao_ve_o_icone(layout):
    trecho = layout.split('id="footer-egg-link"', 1)[1].split("</a>", 1)[0]
    assert 'aria-hidden="true"' in trecho, "o icone e decorativo"
    assert "visually-hidden" in trecho, "o link precisa de um nome acessivel"


def test_texto_do_copyright_continua_inteiro(layout):
    # O gatilho nao pode custar a informacao legal que estava ali.
    assert "&copy; 2026 PetOrlândia." in layout
    assert "Todos os direitos reservados." in layout


# --- estilo e script ------------------------------------------------------


def test_script_carregado_com_versao(layout):
    assert re.search(
        r"js/footer_egg\.js',\s*v='[^']+'",
        layout,
    ), "o script precisa de versao para o cache nao servir o antigo"


def test_gatilho_nao_parece_um_botao():
    css = ESTILO.read_text(encoding="utf-8")
    regra = re.search(r"\.site-footer__egg-key \{([^}]*)\}", css)
    assert regra, "falta a regra que devolve o botao ao texto do rodape"
    corpo = regra.group(1)
    assert "font: inherit" in corpo
    assert "background: none" in corpo
    assert "border: 0" in corpo
    # Esconder o segredo nao pode apagar o foco de quem navega por teclado.
    assert ".site-footer__egg-key:focus-visible" in css


def test_versao_do_css_acompanha_a_mudanca(layout):
    """Sem subir a versao, o visitante recebe o CSS velho.

    O gatilho chegaria nele como um botao com fundo e borda, no meio do
    rodape -- pior do que nao ter o easter egg.
    """
    versao = re.search(r"css/tutor-experience\.css',\s*v='([^']+)'", layout)
    assert versao, "o CSS do rodape precisa de versao"
    assert versao.group(1) != "20260905-avatar", (
        "o CSS mudou nesta alteracao; a versao de cache precisa mudar junto"
    )


def test_descoberta_guardada_nao_derruba_a_pagina():
    """localStorage falha em aba anonima e com site data bloqueado."""
    codigo = SCRIPT.read_text(encoding="utf-8")
    assert codigo.count("try {") >= 2, "toda leitura e escrita precisa de try/catch"
    assert "localStorage" in codigo
