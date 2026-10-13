"""CPF, telefone e RG: nenhuma tela pode recusar o que o banco já guarda.

Contexto do bug que originou este arquivo: a ficha do tutor gravava o CPF com
máscara ("362.430.268-09") e a consulta exigia `pattern="[0-9]{11}"`; a
consulta gravava só dígitos e a ficha exigia a máscara. Quem abria um tutor
salvo pela outra tela via o campo em vermelho ("insira um CPF válido") sem ter
digitado nada, e não conseguia salvar mais nenhum dado. Com o telefone era
pior: 87% dos telefones do banco eram recusados pela consulta.

A correção é `static/js/campos_br.js` (máscara tolerante, marcada com
`data-campo-br`) mais a normalização em `document_utils.py`. O que pode
reintroduzir o problema é um template voltar a pôr `pattern`/`data-mask`
nesses campos — por isso a checagem é estática, varre todos os templates e
aponta arquivo:linha.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_ROOT = PROJECT_ROOT / "templates"

# Campos de texto livre ou de formato variável no banco. `numero` é o número
# do endereço: existe "1680A", "S/N", "120 fundos".
CAMPOS = r"(?:tutor_)?(?:cpf|phone|telefone|celular|rg|numero)"
TAG_INPUT_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE | re.DOTALL)
NOME_RE = re.compile(rf"""\bname\s*=\s*["']{CAMPOS}["']""", re.IGNORECASE)
RIGIDEZ_RE = re.compile(r"""\b(pattern|data-mask)\s*=""", re.IGNORECASE)
# Campo de WTForms: {{ form.cpf(class="...", pattern="...") }}
CAMPO_WTFORMS_RE = re.compile(
    rf"""\.{CAMPOS}\s*\((?:[^()]|\([^()]*\))*\b(pattern|data_mask)\s*=""",
    re.IGNORECASE | re.DOTALL,
)
MARCA_RE = re.compile(r"""data-campo-br\s*=""")
CARREGA_RE = re.compile(r"<script[^>]*js/campos_br\.js")
EXTENDS_RE = re.compile(r"{%-?\s*extends\s+['\"]([^'\"]+)['\"]")
INCLUDE_RE = re.compile(r"{%-?\s*include\s+['\"]([^'\"]+)['\"]")


def _templates() -> dict[str, str]:
    return {
        p.relative_to(TEMPLATES_ROOT).as_posix(): p.read_text(encoding="utf-8", errors="replace")
        for p in TEMPLATES_ROOT.rglob("*.html")
    }


def _linha(texto: str, posicao: int) -> int:
    return texto[:posicao].count("\n") + 1


def _campos_rigidos(texto: str) -> list[tuple[int, str]]:
    achados = []
    for tag in TAG_INPUT_RE.finditer(texto):
        if NOME_RE.search(tag.group(0)) and (rigidez := RIGIDEZ_RE.search(tag.group(0))):
            achados.append((_linha(texto, tag.start()), rigidez.group(1)))
    for chamada in CAMPO_WTFORMS_RE.finditer(texto):
        achados.append((_linha(texto, chamada.start()), chamada.group(1)))
    return achados


def test_varredura_encontra_os_templates():
    """Sanidade: sem arquivos, os testes abaixo passariam vazios."""
    templates = _templates()
    assert len(templates) > 200
    assert sum(1 for texto in templates.values() if MARCA_RE.search(texto)) >= 3


def test_campos_de_documento_e_telefone_nao_tem_formato_rigido():
    """`pattern`/`data-mask` nesses campos recusa o que outra tela gravou.

    Se este teste falhar, tire o atributo e marque o campo com
    `data-campo-br="cpf"`, `"telefone"` ou `"rg"` (static/js/campos_br.js).
    """
    ofensores = [
        f"  templates/{nome}:{linha} ({atributo})"
        for nome, texto in sorted(_templates().items())
        for linha, atributo in _campos_rigidos(texto)
    ]
    assert not ofensores, (
        "Campo de CPF/telefone/RG/número com formato fixo no HTML. O banco guarda esses "
        "dados em mais de um formato; o campo abriria em vermelho:\n" + "\n".join(ofensores)
    )


def test_pagina_com_campo_marcado_carrega_o_script():
    """`data-campo-br` sem o script é um campo sem máscara e sem validação."""
    templates = _templates()
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
    faltando = sorted(
        f"  templates/{nome}" for nome, texto in templates.items()
        if MARCA_RE.search(texto) and nome not in cobertos
    )
    assert not faltando, "Template usa data-campo-br fora de um layout que carrega campos_br.js:\n" + "\n".join(faltando)


@pytest.mark.parametrize(
    "trecho, rigido",
    [
        ('<input name="cpf" pattern="[0-9]{11}">', True),
        ('<input type="tel" id="x"\n  name="phone"\n  pattern="[0-9]{10,11}">', True),
        ('<input name="rg" data-mask="99.999.999-9">', True),
        ('<input name="numero" pattern="\\d*">', True),
        ('{{ addr_form.numero(class="form-control", pattern="\\\\d*") }}', True),
        ('{{ form.cpf(class="form-control", placeholder="000.000.000-00") }}', False),
        ('<input name="cpf" data-campo-br="cpf">', False),
        ('<input name="cep" pattern="\\d{5}-?\\d{3}">', False),
        ('<input name="microchip_number" pattern="[0-9]{15}">', False),
    ],
)
def test_regex_reconhece_campo_rigido(trecho, rigido):
    assert bool(_campos_rigidos(trecho)) is rigido


def test_funcoes_passam_no_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node não disponível para exercitar campos_br.js")
    resultado = subprocess.run(
        [node, str(PROJECT_ROOT / "tests" / "test_campos_br.js")],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=60,
    )
    assert resultado.returncode == 0, f"{resultado.stdout}\n{resultado.stderr}"


# --- servidor: mesmas regras ---------------------------------------------------

def test_formatacao_no_servidor_acompanha_a_do_navegador():
    from document_utils import format_cpf, format_phone_br, normalize_cpf, normalize_phone

    assert format_cpf("36243026809") == "362.430.268-09"
    assert format_cpf("362.430.268-09") == "362.430.268-09"
    assert format_cpf("99999") == "99999"
    assert format_cpf(None) == ""
    assert normalize_cpf("362.430.268-09") == "36243026809"

    for gravado in ("16992690405", "(16) 99269-0405", "(16)992690405", "+5516992690405",
                    "5516992690405", "016992690405"):
        assert format_phone_br(gravado) == "(16) 99269-0405", gravado
        assert normalize_phone(gravado) == "16992690405", gravado
    assert format_phone_br("1638261234") == "(16) 3826-1234"
    # Estrangeiro e incompleto ficam como vieram: nada é inventado.
    assert format_phone_br("+351912345678") == "+351912345678"
    assert normalize_phone("+351912345678") == "+351912345678"
    assert format_phone_br("999999999") == "999999999"


def test_mesmo_dado_com_outra_pontuacao_nao_conta_como_alteracao():
    from document_utils import same_cpf, same_phone

    assert same_cpf("362.430.268-09", "36243026809")
    assert not same_cpf("362.430.268-09", "36243026800")
    assert same_cpf("", None)
    assert same_phone("(16) 99269-0405", "+5516992690405")
    assert same_phone("16992690405", "(16)992690405")
    assert not same_phone("(16) 99269-0405", "(16) 99269-0406")
    assert same_phone("999999999", "99999-9999")


def test_filtros_estao_registrados():
    from template_filters import _FILTERS

    assert _FILTERS["cpf_br"]("36243026809") == "362.430.268-09"
    assert _FILTERS["telefone_br"]("+5516992690405") == "(16) 99269-0405"
