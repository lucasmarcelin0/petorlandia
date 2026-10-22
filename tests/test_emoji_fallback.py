"""Emojis em computadores sem fonte colorida (ex.: Windows 7).

O layout carrega static/js/emoji_fallback.js; ele só baixa o Twemoji quando o
navegador não desenha emoji colorido. Estes testes protegem a ligação com o
layout, a versão fixa com SRI e a liberação do CDN na CSP.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "static/js/emoji_fallback.js").read_text(encoding="utf-8")


def test_layout_carrega_o_script_de_emoji():
    layout = (ROOT / "templates/layout.html").read_text(encoding="utf-8")
    assert re.search(r"filename='js/emoji_fallback\.js'[^>]*\)\s*}}\"\s+defer", layout)


def test_twemoji_tem_versao_fixa_e_integridade():
    assert "https://cdn.jsdelivr.net/npm/@twemoji/api@15.1.0/dist/twemoji.min.js" in SCRIPT
    assert re.search(r"'sha384-[A-Za-z0-9+/=]{64}'", SCRIPT)
    assert "script.crossOrigin = 'anonymous'" in SCRIPT
    # Só baixa quando o navegador não desenha emoji colorido.
    assert SCRIPT.index("if (hasColorEmoji()) return;") < SCRIPT.index("document.head.appendChild(script)")


def test_csp_libera_script_e_imagens_do_cdn(client):
    policy = client.get("/").headers.get("Content-Security-Policy", "")
    script_src = re.search(r"script-src ([^;]+)", policy).group(1)
    img_src = re.search(r"img-src ([^;]+)", policy).group(1)
    assert "https://cdn.jsdelivr.net" in script_src
    assert "https:" in img_src.split()
