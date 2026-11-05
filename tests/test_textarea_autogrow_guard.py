"""Toda caixa de texto (textarea) cresce com o que está escrito.

Contexto: a caixa de mensagem ficava com três linhas e o resto do texto só
aparecia rolando dentro dela; o mesmo valia para anamnese, prescrição,
observações e qualquer outro campo longo. `static/js/autogrow.js` ajusta a
altura de toda textarea da página (inclusive as que aparecem depois ou são
preenchidas por script), mas só nas páginas que carregam o script.

O que pode reintroduzir o problema é uma página nova (ou um layout-base novo)
que não carregue o script. A checagem é estática: varre todos os templates e
aponta o arquivo.
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_ROOT = PROJECT_ROOT / "templates"
STATIC_JS = PROJECT_ROOT / "static" / "js"

CARREGA_RE = re.compile(r"<script[^>]*js/autogrow\.js")
TEXTAREA_RE = re.compile(r"<textarea\b", re.IGNORECASE)
DOCUMENTO_RE = re.compile(r"<html\b", re.IGNORECASE)
EXTENDS_RE = re.compile(r"{%-?\s*extends\s+['\"]([^'\"]+)['\"]")
INCLUDE_RE = re.compile(r"{%-?\s*(?:include|import|from)\s+['\"]([^'\"]+)['\"]")
SCRIPT_JS_RE = re.compile(r"""filename\s*=\s*['"]js/([\w./-]+\.js)['"]""")
CRIA_TEXTAREA_JS_RE = re.compile(r"<textarea\b|createElement\(\s*['\"]textarea['\"]\s*\)", re.IGNORECASE)

# Textareas que só existem por um instante para copiar texto (fora da tela).
JS_SO_COPIA = {"sfa_atlas_nav.js", "sfa_atlas_route.js"}


def _templates() -> dict[str, str]:
    return {
        p.relative_to(TEMPLATES_ROOT).as_posix(): p.read_text(encoding="utf-8", errors="replace")
        for p in TEMPLATES_ROOT.rglob("*.html")
    }


def _scripts_que_criam_textarea() -> set[str]:
    return {
        p.relative_to(STATIC_JS).as_posix()
        for p in STATIC_JS.rglob("*.js")
        if p.name not in JS_SO_COPIA
        and p.name != "autogrow.js"
        and CRIA_TEXTAREA_JS_RE.search(p.read_text(encoding="utf-8", errors="replace"))
    }


def _cobertos(templates: dict[str, str]) -> set[str]:
    """Templates renderidos dentro de uma página que carrega autogrow.js."""
    filhos: dict[str, set[str]] = {}
    for nome, texto in templates.items():
        for pai in EXTENDS_RE.findall(texto):
            filhos.setdefault(pai, set()).add(nome)

    def familia(nome: str, vistos: set[str]) -> set[str]:
        if nome in vistos or nome not in templates:
            return vistos
        vistos.add(nome)
        for filho in filhos.get(nome, ()):
            familia(filho, vistos)
        for incluido in INCLUDE_RE.findall(templates[nome]):
            familia(incluido, vistos)
        return vistos

    cobertos: set[str] = set()
    for nome, texto in templates.items():
        if CARREGA_RE.search(texto):
            cobertos |= familia(nome, set())
    return cobertos


def test_varredura_encontra_os_templates():
    """Sanidade: sem arquivos, os testes abaixo passariam vazios."""
    templates = _templates()
    assert len(templates) > 200
    assert sum(1 for texto in templates.values() if TEXTAREA_RE.search(texto)) >= 40
    assert len(_cobertos(templates)) > 200
    assert _scripts_que_criam_textarea()


def test_layouts_base_carregam_o_script():
    """Layout-base sem o script deixa travadas as textareas de todas as filhas,
    inclusive as de formulários WTForms ({{ form.campo() }}), que a varredura
    por `<textarea` não enxerga."""
    templates = _templates()
    pais = {pai for texto in templates.values() for pai in EXTENDS_RE.findall(texto)}
    faltando = sorted(
        f"  templates/{nome}" for nome in pais
        if nome in templates and DOCUMENTO_RE.search(templates[nome]) and not CARREGA_RE.search(templates[nome])
    )
    assert not faltando, (
        "Layout-base sem js/autogrow.js; as caixas de texto das páginas filhas não crescem:\n"
        + "\n".join(faltando)
    )


def test_pagina_com_textarea_carrega_o_script():
    templates = _templates()
    cobertos = _cobertos(templates)
    scripts = _scripts_que_criam_textarea()
    faltando = []
    for nome, texto in sorted(templates.items()):
        if nome in cobertos:
            continue
        if TEXTAREA_RE.search(texto):
            faltando.append(f"  templates/{nome} (<textarea>)")
        for script in SCRIPT_JS_RE.findall(texto):
            if script in scripts:
                faltando.append(f"  templates/{nome} (static/js/{script} cria textarea)")
    assert not faltando, (
        "Página com caixa de texto que não carrega js/autogrow.js (nem herda de um layout que carregue):\n"
        + "\n".join(faltando)
    )


def test_script_cobre_textareas_novas_e_preenchidas_por_codigo():
    """As três portas por onde uma textarea fica com texto escondido."""
    fonte = (STATIC_JS / "autogrow.js").read_text(encoding="utf-8")
    assert "querySelectorAll('textarea')" in fonte, "o script deve valer para toda textarea, não só as marcadas"
    assert "MutationObserver" in fonte, "textareas inseridas depois (modais, fetch) precisam crescer"
    assert "HTMLTextAreaElement.prototype, 'value'" in fonte, "texto colocado por script precisa crescer"
    assert "IntersectionObserver" in fonte, "campo oculto ao carregar precisa crescer ao aparecer"
