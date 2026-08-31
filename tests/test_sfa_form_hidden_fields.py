"""Guarda de classe: campos condicionais precisam sumir da tela, nao so desabilitar.

O bug original era de cascata: `.field { display: grid; }` vencia a regra do
agente de usuario para `[hidden]`, entao o campo condicional continuava visivel
com os controles desabilitados e o participante achava que o formulario travou.
Em vez de testar um campo por vez, este teste valida a propriedade que faz
qualquer campo condicional sumir, presente e futuro.
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "templates" / "sfa" / "t0_form.html"


def _stylesheet(markup):
    blocos = re.findall(r"<style>(.*?)</style>", markup, re.DOTALL)
    assert blocos, "o formulario T0 precisa de um bloco <style>"
    return "\n".join(blocos)


def _regras(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def _declaracoes_de_display(css):
    for seletor, corpo in _regras(css):
        for declaracao in corpo.split(";"):
            propriedade, _, valor = declaracao.partition(":")
            if propriedade.strip().lower() == "display":
                yield seletor.strip(), valor.strip().lower()


def test_hidden_vence_qualquer_display_do_formulario():
    css = _stylesheet(TEMPLATE.read_text(encoding="utf-8"))
    displays = list(_declaracoes_de_display(css))

    guardas = [
        (seletor, valor)
        for seletor, valor in displays
        if "[hidden]" in seletor and valor.startswith("none") and "!important" in valor
    ]
    assert guardas, (
        "o formulario precisa de uma regra `[hidden] { display: none !important; }` "
        "para que os campos condicionais sumam em vez de ficarem visiveis e desabilitados"
    )

    concorrentes = [
        (seletor, valor)
        for seletor, valor in displays
        if "!important" in valor and "[hidden]" not in seletor
    ]
    assert not concorrentes, (
        "regras com display !important fora da guarda de [hidden] podem manter um "
        f"campo oculto na tela: {concorrentes}"
    )


def test_campos_condicionais_sao_marcados_no_html():
    markup = TEMPLATE.read_text(encoding="utf-8")
    assert "data-visible-if" in markup, (
        "os campos condicionais precisam expor data-visible-if para o script de condicoes"
    )
    assert "sfa_form_conditions.js" in markup, (
        "o formulario precisa carregar o script que aplica as condicoes"
    )
