"""Guarda global: todo formulário POST precisa carregar token CSRF.

Contexto do bug que originou este arquivo: o formulário de exclusão em
`animais/editar_animal.html` era um POST sem token. Como o app usa
`CSRFProtect` global, o submit caía no handler de CSRFError, que mostra
"Sua sessão foi atualizada. Confira os dados e envie o formulário novamente."
e redireciona de volta — o animal nunca era excluído e a mensagem não deixava
claro que a causa era o token ausente.

A suíte inteira roda com `WTF_CSRF_ENABLED=False`, então nenhum teste
funcional conseguia enxergar esse problema: os POSTs dos testes passam sem
token por construção. Por isso a checagem aqui é *estática* — varre os
templates e cobre TODAS as telas de uma vez, em vez de depender de um teste
funcional por rota.

Se este teste falhar, a correção é adicionar ao formulário:

    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

ou, quando existir um WTForm no contexto, `{{ form.hidden_tag() }}`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_ROOT = PROJECT_ROOT / "templates"

FORM_OPEN_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE | re.DOTALL)
FORM_CLOSE_RE = re.compile(r"</form\s*>", re.IGNORECASE)
METHOD_POST_RE = re.compile(r"method\s*=\s*[\"']?\s*post", re.IGNORECASE)
INCLUDE_RE = re.compile(r"{%-?\s*include\s+(.+?)\s*-?%}", re.DOTALL)
INCLUDE_LITERAL_RE = re.compile(r"^[\"']([^\"']+)[\"']")

# Marcadores que provam que o token acompanha o POST.
TOKEN_MARKERS = ("csrf_token", "hidden_tag()", "csrf_field")

# Formulários que podem ficar sem token porque a rota de destino é
# explicitamente `@csrf.exempt`. Chave = template, valor = motivo.
# Cada entrada aqui é uma decisão consciente, não um "TODO".
CSRF_EXEMPT_TEMPLATES = {
    "sfa/review_form.html": (
        "POST vai para sfa_routes.revisao_formulario, decorada com @csrf.exempt "
        "(formulário público de revisão, sem sessão autenticada)."
    ),
    "sfa/review_charts.html": (
        "POST vai para sfa_routes.revisao_graficos, decorada com @csrf.exempt."
    ),
}

MAX_INCLUDE_DEPTH = 5


def _resolve_include_targets(body: str) -> tuple[list[Path], bool]:
    """Devolve os includes literais do trecho e se há include dinâmico.

    Include dinâmico (`{% include variavel %}`) não dá para resolver
    estaticamente; sinalizamos para o chamador não acusar falso positivo.
    """
    targets: list[Path] = []
    has_dynamic = False
    for raw in INCLUDE_RE.findall(body):
        literal = INCLUDE_LITERAL_RE.match(raw.strip())
        if literal:
            targets.append(TEMPLATES_ROOT / literal.group(1))
        else:
            has_dynamic = True
    return targets, has_dynamic


def _has_token(body: str, depth: int = 0) -> bool | None:
    """True = token presente, False = ausente, None = indeterminado.

    Indeterminado acontece quando o formulário inclui um template escolhido em
    runtime; nesse caso a checagem estática se abstém em vez de mentir.
    """
    if any(marker in body for marker in TOKEN_MARKERS):
        return True
    if depth >= MAX_INCLUDE_DEPTH:
        return None

    targets, has_dynamic = _resolve_include_targets(body)
    for target in targets:
        if not target.is_file():
            # Include apontando para arquivo inexistente: outro problema,
            # mas não é este teste que deve falhar por isso.
            has_dynamic = True
            continue
        nested = _has_token(target.read_text(encoding="utf-8", errors="replace"), depth + 1)
        if nested is True:
            return True
        if nested is None:
            has_dynamic = True

    return None if has_dynamic else False


def _iter_post_forms(text: str):
    """Itera os formulários POST de um template: (linha, open_tag, corpo)."""
    pos = 0
    while True:
        match = FORM_OPEN_RE.search(text, pos)
        if not match:
            return
        open_tag = match.group(0)
        close = FORM_CLOSE_RE.search(text, match.end())
        body_end = close.start() if close else len(text)
        if METHOD_POST_RE.search(open_tag):
            line = text.count("\n", 0, match.start()) + 1
            yield line, " ".join(open_tag.split()), text[match.end():body_end]
        pos = match.end()


def _template_paths() -> list[Path]:
    return sorted(TEMPLATES_ROOT.rglob("*.html"))


def test_templates_directory_is_present():
    """Sanidade: se a varredura não achar templates, o guard viraria no-op."""
    paths = _template_paths()
    assert len(paths) > 50, f"varredura encontrou apenas {len(paths)} templates"


def test_every_post_form_carries_csrf_token():
    """Nenhum formulário POST pode ir para o servidor sem token CSRF."""
    offenders: list[str] = []

    for path in _template_paths():
        rel = path.relative_to(PROJECT_ROOT / "templates").as_posix()
        if rel in CSRF_EXEMPT_TEMPLATES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line, open_tag, body in _iter_post_forms(text):
            if _has_token(body) is False:
                offenders.append(f"  templates/{rel}:{line}\n      {open_tag[:110]}")

    assert not offenders, (
        "Formulário POST sem token CSRF — o submit vai falhar com "
        "'Sua sessão foi atualizada. Confira os dados e envie o formulário novamente.'\n"
        "Adicione <input type=\"hidden\" name=\"csrf_token\" value=\"{{ csrf_token() }}\">"
        " ou {{ form.hidden_tag() }}:\n\n" + "\n".join(offenders)
    )


def test_csrf_exempt_allowlist_stays_justified():
    """A allowlist não pode acumular entradas mortas ou sem motivo escrito."""
    for rel, reason in CSRF_EXEMPT_TEMPLATES.items():
        assert (TEMPLATES_ROOT / rel).is_file(), (
            f"{rel} está na allowlist de CSRF mas não existe mais; remova a entrada."
        )
        assert len(reason) > 30, f"{rel} precisa de um motivo explícito na allowlist."


def test_exempt_templates_really_point_to_exempt_routes():
    """Confirma que a allowlist reflete @csrf.exempt de verdade no código."""
    sfa_source = (PROJECT_ROOT / "blueprints" / "sfa.py").read_text(
        encoding="utf-8", errors="replace"
    )
    for view_name in ("def revisao_formulario", "def revisao_graficos"):
        idx = sfa_source.find(view_name)
        assert idx != -1, f"{view_name} não encontrada em blueprints/sfa.py"
        # O decorator fica nas linhas imediatamente acima da definição.
        preceding = sfa_source[max(0, idx - 300):idx]
        assert "@csrf.exempt" in preceding, (
            f"{view_name} não está mais @csrf.exempt; remova-a da allowlist e "
            "adicione token CSRF ao template correspondente."
        )


# --- Guarda estática do parser -------------------------------------------------
# Sem estes casos, um parser quebrado deixaria o teste acima passar vazio.

@pytest.mark.parametrize(
    "snippet, expected_offender",
    [
        ('<form method="POST"><button>x</button></form>', True),
        ('<form method="post"><button>x</button></form>', True),
        ("<form method=post><button>x</button></form>", True),
        ('<form method="POST">{{ form.hidden_tag() }}</form>', False),
        (
            '<form method="POST">'
            '<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"></form>',
            False,
        ),
        ('<form method="GET"><button>x</button></form>', False),
        ('<form action="/x"><button>x</button></form>', False),
    ],
)
def test_parser_flags_only_tokenless_post_forms(snippet, expected_offender):
    forms = list(_iter_post_forms(snippet))
    if not METHOD_POST_RE.search(snippet.split(">")[0]):
        assert not forms
        assert expected_offender is False
        return
    assert forms, f"parser não reconheceu o form POST em {snippet!r}"
    _, _, body = forms[0]
    assert (_has_token(body) is False) is expected_offender


def test_parser_follows_includes_for_token():
    """O token pode chegar via {% include %}; isso não é violação."""
    body = "{% include 'partials/schedule_form_body.html' %}"
    assert _has_token(body) is True


def test_parser_abstains_on_dynamic_include():
    """Include resolvido em runtime => indeterminado, nunca acusação falsa."""
    assert _has_token("{% include partial_escolhido %}") is None
