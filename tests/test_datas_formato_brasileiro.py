"""Guarda global: toda data que o usuário vê fica no padrão brasileiro.

Contexto do bug que originou este arquivo: o `<input type="date">` é desenhado
pelo NAVEGADOR, no idioma dele. Num Chrome em inglês a tela de agendamento
mostrava "mm/dd/yyyy" mesmo com `<html lang="pt-BR">`, com `lang="pt-BR"` no
próprio campo e com o rótulo "Data (dd/mm/aaaa)" ao lado. Não existe atributo
HTML que mude isso: por isso `static/js/date_br.js` troca cada campo nativo
(date, datetime-local, month) por um espelho em dd/mm/aaaa, mantendo o valor
técnico em ISO. O mesmo vale para as horas em `static/js/time24.js`.

Como a correção é um script global, o que pode reintroduzir o problema é uma
página nova que não o carregue, ou um JavaScript/Jinja que formate data por
conta própria. São centenas de rotas: um teste funcional por tela não escala.
Então a checagem aqui é *estática* e varre o repositório inteiro atrás dessas
assinaturas, apontando arquivo:linha.

O comportamento do componente em si é exercitado em `tests/test_date_br.js`
(Node, conversões) e em `tests/test_date_br_browser.py` (Chromium em inglês).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_ROOT = PROJECT_ROOT / "templates"
STATIC_ROOT = PROJECT_ROOT / "static"

SCRIPT_DATA = "js/date_br.js"
SCRIPT_HORA = "js/time24.js"
# Tem de ser a tag <script>, não uma menção em comentário.
CARREGA_DATA_RE = re.compile(r"<script[^>]*js/date_br\.js")

EXTENDS_RE = re.compile(r"{%-?\s*extends\s+['\"]([^'\"]+)['\"]")
INCLUDE_RE = re.compile(r"{%-?\s*include\s+['\"]([^'\"]+)['\"]")
DOCUMENTO_RE = re.compile(r"<html\b", re.IGNORECASE)
CAMPO_RE = re.compile(r"<(input|select|textarea)\b|<form\b", re.IGNORECASE)
CAMPO_DE_DATA_RE = re.compile(
    r"""type\s*=\s*["']?(date|datetime-local|month|week)\b"""
    r"""|\btype\s*:\s*["'](date|datetime-local|month|week)["']""",
    re.IGNORECASE,
)
SEMANA_RE = re.compile(r"""type\s*=\s*["']?week\b|\btype\s*:\s*["']week["']""", re.IGNORECASE)

# Páginas HTML servidas direto do static (SPAs), com o JS que elas carregam.
PAGINAS_ESTATICAS = {
    STATIC_ROOT / "sim_portal" / "index.html": [STATIC_ROOT / "sim_portal" / "app.js"],
}

# Documentos sem script de data, cada um com o motivo escrito. Não é lista de
# "pendências": é decisão consciente, e o teste falha se o motivo deixar de valer.
DOCUMENTOS_SEM_CAMPOS = {
    "static/offline.html": "página de fallback offline: texto fixo, sem formulário.",
}


def _arquivos(raiz: Path, sufixo: str) -> list[Path]:
    return sorted(p for p in raiz.rglob(f"*{sufixo}") if "vendor" not in p.parts)


def _texto(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _templates() -> dict[str, str]:
    return {
        p.relative_to(TEMPLATES_ROOT).as_posix(): _texto(p)
        for p in TEMPLATES_ROOT.rglob("*.html")
    }


def _js_do_app() -> list[Path]:
    arquivos = [
        p
        for p in _arquivos(STATIC_ROOT, ".js")
        if not p.name.endswith(".min.js") and "vendor" not in p.parts
    ]
    arquivos += _arquivos(PROJECT_ROOT / "blueprints", ".js")
    return sorted(arquivos)


def _fontes_com_js() -> list[Path]:
    """Arquivos onde pode haver JavaScript do produto: .js e templates."""
    return _js_do_app() + sorted(TEMPLATES_ROOT.rglob("*.html"))


def _familia(templates: dict[str, str]) -> dict[str, set[str]]:
    """Para cada documento, os templates que podem acabar dentro dele.

    Um layout recebe o conteúdo de quem o estende (transitivamente) e de quem
    ele inclui; é lá que os campos de data aparecem.
    """
    filhos: dict[str, set[str]] = {}
    for nome, texto in templates.items():
        for pai in EXTENDS_RE.findall(texto):
            filhos.setdefault(pai, set()).add(nome)

    def fechamento(nome: str, vistos: set[str]) -> set[str]:
        if nome in vistos or nome not in templates:
            return vistos
        vistos.add(nome)
        for filho in filhos.get(nome, ()):  # quem estende
            fechamento(filho, vistos)
        for incluido in INCLUDE_RE.findall(templates[nome]):  # quem é incluído
            fechamento(incluido, vistos)
        return vistos

    return {nome: fechamento(nome, set()) for nome in templates}


def _documentos(templates: dict[str, str]) -> list[str]:
    return [nome for nome, texto in templates.items() if DOCUMENTO_RE.search(texto)]


def test_varredura_encontra_os_arquivos():
    """Sanidade: sem arquivos, todos os testes abaixo passariam vazios."""
    templates = _templates()
    assert len(templates) > 200, f"apenas {len(templates)} templates encontrados"
    assert len(_documentos(templates)) > 10
    assert len(_js_do_app()) > 20


def test_componente_de_data_existe():
    assert (STATIC_ROOT / "js" / "date_br.js").is_file()
    assert (STATIC_ROOT / "js" / "time24.js").is_file()
    assert (STATIC_ROOT / "vendor" / "flatpickr" / "flatpickr.min.js").is_file()
    assert (STATIC_ROOT / "vendor" / "flatpickr" / "plugins" / "monthSelect" / "index.js").is_file()


def test_toda_pagina_com_formulario_carrega_o_formato_brasileiro():
    """Página com campo hoje pode ganhar um campo de data amanhã.

    Se este teste falhar, inclua no documento (ou no layout que ele usa):

        <script src="{{ url_for('static', filename='js/date_br.js') }}" defer></script>
        <script type="module" src="{{ url_for('static', filename='js/time24.js') }}"></script>
    """
    templates = _templates()
    familia = _familia(templates)
    faltando: list[str] = []

    for documento in _documentos(templates):
        parentes = familia[documento]
        tem_campo = any(CAMPO_RE.search(templates[nome]) for nome in parentes)
        if not tem_campo:
            continue
        carrega = any(CARREGA_DATA_RE.search(templates[nome]) for nome in parentes)
        if not carrega:
            exemplo = next(
                (
                    f"{nome}:{templates[nome][: m.start()].count(chr(10)) + 1}"
                    for nome in sorted(parentes)
                    if (m := CAMPO_DE_DATA_RE.search(templates[nome]))
                ),
                "campos de formulário",
            )
            faltando.append(f"  templates/{documento} (ex.: {exemplo})")

    for pagina, scripts in PAGINAS_ESTATICAS.items():
        texto = _texto(pagina)
        if not CARREGA_DATA_RE.search(texto):
            faltando.append(f"  {pagina.relative_to(PROJECT_ROOT).as_posix()}")

    assert not faltando, (
        "Página sem static/js/date_br.js: os campos de data vão aparecer no formato do "
        "NAVEGADOR (mm/dd/yyyy num Chrome em inglês).\n" + "\n".join(faltando)
    )


SCRIPT_SRC_RE = re.compile(r"<script[^>]*\bsrc=[^>]*>", re.IGNORECASE)
# O wrapper de CSRF tem de ser o primeiro de todos (tests/test_csrf_ajax_guard.py).
SCRIPTS_ANTES = ("csrf_fetch.js",)


def test_componente_roda_antes_dos_scripts_da_pagina():
    """`window.PetDateBR` precisa existir quando a página começa a rodar.

    Vários scripts de tela (contabilidade, portal SIM, agenda) formatam data
    ainda durante o carregamento. Com `defer`, o componente só rodaria depois
    deles e essas telas quebrariam com "PetDateBR is undefined".
    """
    documentos = {
        f"templates/{nome}": texto
        for nome, texto in _templates().items()
        if CARREGA_DATA_RE.search(texto)
    }
    documentos.update(
        {pagina.relative_to(PROJECT_ROOT).as_posix(): _texto(pagina) for pagina in PAGINAS_ESTATICAS}
    )
    problemas = []
    for nome, texto in documentos.items():
        tag = CARREGA_DATA_RE.search(texto)
        fim_da_tag = texto.find(">", tag.start())
        if re.search(r"\b(defer|async)\b", texto[tag.start(): fim_da_tag]):
            problemas.append(f"  {nome}: a tag do date_br.js não pode ter defer/async")
        for outro in SCRIPT_SRC_RE.finditer(texto[: tag.start()]):
            if any(permitido in outro.group(0) for permitido in SCRIPTS_ANTES):
                continue
            linha = texto[: outro.start()].count("\n") + 1
            problemas.append(f"  {nome}:{linha} script carregado antes do date_br.js: {outro.group(0)[:80]}")
    assert not problemas, "Ordem de carregamento do componente de datas:\n" + "\n".join(problemas)


def test_paginas_estaticas_que_criam_campos_de_data_carregam_o_script():
    """SPA servida do static também precisa do componente."""
    for pagina, scripts in PAGINAS_ESTATICAS.items():
        cria_data = any(CAMPO_DE_DATA_RE.search(_texto(js)) for js in scripts)
        if cria_data:
            assert CARREGA_DATA_RE.search(_texto(pagina)), f"{pagina} cria campo de data sem carregar {SCRIPT_DATA}"


def test_nao_existe_campo_de_data_sem_suporte():
    """`type="week"` não é coberto pelo componente (e não tem formato brasileiro)."""
    ofensores = []
    for path in _fontes_com_js():
        for numero, linha in enumerate(_texto(path).splitlines(), 1):
            if SEMANA_RE.search(linha) and "date_br.js" not in path.name:
                ofensores.append(f"  {path.relative_to(PROJECT_ROOT).as_posix()}:{numero}")
    assert not ofensores, (
        "`type=\"week\"` não tem apresentação brasileira nem suporte em date_br.js.\n"
        + "\n".join(ofensores)
    )


# --- formatação em JavaScript -------------------------------------------------

SEM_LOCALE_RE = re.compile(
    r"\.toLocale(?:Date|Time)?String\(\s*(?:\)|undefined|\[\]|navigator|['\"](?!pt-BR)[a-z]{2})"
    r"|Intl\.DateTimeFormat\(\s*(?:\)|undefined|\[\]|navigator|['\"](?!pt-BR)[a-z]{2})"
)
# `new Date()` é o agora em UTC: fatiar a data dele devolve o dia seguinte das
# 21h à meia-noite no Brasil. (Converter uma data já ajustada ao fuso local é
# outra coisa e não entra aqui.)
HOJE_EM_UTC_RE = re.compile(
    r"new\s+Date\(\s*\)\s*\.\s*toISOString\(\)\s*\.\s*"
    r"(?:slice\(\s*0\s*,\s*10\s*\)|split\(\s*['\"]T['\"]\s*\)\s*\[\s*0\s*\])"
)

# Cada isenção com o motivo escrito.
LOCALE_PERMITIDO = {
    "static/js/time24.js": "detecta se o navegador usa relógio de 12h; não formata nada para o usuário.",
}
HOJE_EM_UTC_PERMITIDO = {
    "blueprints/sim_static/app.js": (
        "cópia morta do portal SIM: blueprints/sim.py serve static/sim_portal, "
        "e esta pasta não é entregue por nenhuma rota."
    ),
}


def _ofensores(regex: re.Pattern[str], permitidos: dict[str, str]) -> list[str]:
    achados = []
    for path in _fontes_com_js():
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if rel in permitidos:
            continue
        for numero, linha in enumerate(_texto(path).splitlines(), 1):
            if regex.search(linha):
                achados.append(f"  {rel}:{numero}\n      {linha.strip()[:110]}")
    return achados


def test_js_nao_formata_data_no_idioma_do_navegador():
    """`toLocaleDateString()` sem locale mostra 9/22/2026 para quem usa inglês."""
    ofensores = _ofensores(SEM_LOCALE_RE, LOCALE_PERMITIDO)
    assert not ofensores, (
        "Formatação dependente do idioma do navegador. Passe 'pt-BR' explicitamente "
        "(ou use window.PetDateBR.toDisplay):\n" + "\n".join(ofensores)
    )


def test_js_nao_calcula_hoje_em_utc():
    """`new Date().toISOString().slice(0,10)` vira o dia seguinte após as 21h."""
    ofensores = _ofensores(HOJE_EM_UTC_RE, HOJE_EM_UTC_PERMITIDO)
    assert not ofensores, (
        "Data do dia calculada em UTC: das 21h à meia-noite isso devolve amanhã. "
        "Use window.PetDateBR.todayIso():\n" + "\n".join(ofensores)
    )


def test_permissoes_continuam_justificadas():
    """Isenção só vale com arquivo existente e motivo escrito."""
    for rel, motivo in {**LOCALE_PERMITIDO, **HOJE_EM_UTC_PERMITIDO}.items():
        assert (PROJECT_ROOT / rel).is_file(), f"{rel} não existe mais; remova a isenção."
        assert len(motivo) > 30, f"{rel} precisa de um motivo explícito."
    for rel, motivo in DOCUMENTOS_SEM_CAMPOS.items():
        assert (PROJECT_ROOT / rel).is_file(), f"{rel} não existe mais; remova a entrada."
        assert len(motivo) > 20, f"{rel} precisa de um motivo explícito."


CALENDARIO_RE = re.compile(r"new\s+FullCalendar\.Calendar\(")


def test_calendarios_em_portugues():
    """FullCalendar sem `locale` cai no inglês ("September 2026", "10a")."""
    ofensores = []
    for path in sorted(TEMPLATES_ROOT.rglob("*.html")):
        texto = _texto(path)
        if not CALENDARIO_RE.search(texto):
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        for match in CALENDARIO_RE.finditer(texto):
            trecho = texto[match.end(): match.end() + 900]
            if "locale: 'pt-br'" not in trecho and 'locale: "pt-br"' not in trecho:
                ofensores.append(f"  {rel}:{texto[: match.start()].count(chr(10)) + 1} sem locale pt-br")
        if "locales/pt-br.global.min.js" not in texto:
            ofensores.append(f"  {rel}: não carrega o arquivo de locale pt-br do FullCalendar")
    assert not ofensores, "Calendário em inglês:\n" + "\n".join(ofensores)


# --- formatação no servidor ---------------------------------------------------

def test_filtro_data_br_cobre_data_hora_e_texto_iso():
    from datetime import date, datetime

    from template_filters import data_br

    assert data_br(date(2026, 9, 22)) == "22/09/2026"
    assert data_br(datetime(2026, 9, 22, 8, 5)) == "22/09/2026 08:05"
    assert data_br("2026-09-22") == "22/09/2026"
    assert data_br("2026-09-22T13:04:11.238+00:00") == "22/09/2026 13:04"
    assert data_br("2026-09-22", com_hora=False) == "22/09/2026"
    # O que não é data reconhecível volta intacto: a tela não pode perder o valor.
    assert data_br("em investigação") == "em investigação"
    assert data_br("22/09/2026") == "22/09/2026"
    assert data_br(None) == ""


def test_filtro_data_br_esta_registrado():
    from template_filters import _FILTERS

    assert "data_br" in _FILTERS


EXPRESSAO_RE = re.compile(r"\{\{(.+?)\}\}", re.S)
NOME_DE_DATA_RE = re.compile(
    r"(?:^|[._])(data|date|dia|inicio|fim|nascimento|vencimento|validade|week|mes|\w+_em|\w+_at)$",
    re.IGNORECASE,
)

# `{{ campo }}` cru que já chega formatado do servidor. Cada entrada é uma
# verificação feita, não um "depois eu vejo": (template, expressão) -> motivo.
DATAS_JA_FORMATADAS_NO_SERVIDOR = {
    ("agendamentos/edit_vet_schedule.html", "grupo.dia"): "dia_semana: nome do dia (segunda-feira), não é data.",
    ("veterinarios/vet_detail.html", "grupo.dia"): "dia_semana: nome do dia, não é data.",
    ("partials/clinic_veterinarios_tab.html", "dia"): "dia_semana: nome do dia, não é data.",
    ("sfa/analise_respostas.html", "analise.generated_at"): "blueprints/sfa.py já formata em %d/%m/%Y %H:%M.",
    ("sfa/analise_respostas.html", "row.t0_data"): "services/sfa_service.py formata com formatar_data().",
    ("sfa/analise_respostas.html", "row.t7_data"): "services/sfa_service.py formata com formatar_data().",
    ("sfa/analise_respostas.html", "row.t30_data"): "services/sfa_service.py formata com formatar_data().",
    ("sfa/paciente_detail.html", "form.submitted_at"): "services/sfa_service.py entrega o texto já formatado.",
    ("sfa/print_dashboard_testes.html", "generated_at"): "blueprints/sfa.py formata antes de renderizar.",
    ("sfa/print_form_questions.html", "generated_at"): "blueprints/sfa.py formata antes de renderizar.",
    ("sfa/review_summary.html", "comment.created_at"): "blueprints/sfa.py formata em %d/%m/%Y %H:%M.",
    ("sfa/review_summary.html", "entry.created_at"): "blueprints/sfa.py formata em %d/%m/%Y %H:%M.",
}


def _dentro_de_tag(texto: str, posicao: int) -> bool:
    return texto.rfind("<", 0, posicao) > texto.rfind(">", 0, posicao)


def test_jinja_nao_imprime_data_crua_no_texto():
    """`{{ consulta.created_at }}` sai como "2026-09-22 10:30:00" na tela.

    Se este teste falhar, use `|data_br` (ou formate no servidor). Só olhamos
    texto visível: ISO dentro de atributo (`value=`, `data-*`) é o esperado.
    """
    templates = _templates()
    ofensores = []
    for nome, texto in templates.items():
        for match in EXPRESSAO_RE.finditer(texto):
            expressao = match.group(1).strip()
            if any(marca in expressao for marca in ("|", "(", " if ", " or ", "strftime")):
                continue
            if _dentro_de_tag(texto, match.start()):
                continue
            alvo = expressao.rsplit(".", 1)[-1]
            if not NOME_DE_DATA_RE.search(alvo):
                continue
            if (nome, expressao) in DATAS_JA_FORMATADAS_NO_SERVIDOR:
                continue
            linha = texto[: match.start()].count("\n") + 1
            ofensores.append(f"  templates/{nome}:{linha}  {{{{ {expressao} }}}}")
    assert not ofensores, (
        "Data impressa sem formatação (sai em aaaa-mm-dd). Use |data_br, ou registre "
        "em DATAS_JA_FORMATADAS_NO_SERVIDOR se o valor já vier formatado:\n" + "\n".join(ofensores)
    )


def test_allowlist_de_datas_no_servidor_continua_valendo():
    templates = _templates()
    for (nome, expressao), motivo in DATAS_JA_FORMATADAS_NO_SERVIDOR.items():
        assert nome in templates, f"{nome} não existe mais; remova a entrada."
        assert f"{{{{ {expressao} }}}}" in templates[nome], (
            f"{nome} não imprime mais {{{{ {expressao} }}}}; remova a entrada."
        )
        assert len(motivo) > 20, f"{nome}/{expressao} precisa de um motivo explícito."


MODELVIEW_RE = re.compile(r"^class\s+(\w+)\(([^)]*)\):", re.MULTILINE)


def test_admin_mostra_datas_em_portugues():
    """Sem isso o Flask-Admin lista "2026-09-22 10:30:00" em toda tabela."""
    from datetime import date, datetime

    import admin as admin_module

    assert admin_module.TIPOS_DATA_BR[date](None, date(2026, 9, 22), "x") == "22/09/2026"
    assert admin_module.TIPOS_DATA_BR[datetime](None, datetime(2026, 9, 22, 10, 30), "x") == "22/09/2026 10:30"

    fonte = _texto(PROJECT_ROOT / "admin.py")
    ofensores = []
    for match in MODELVIEW_RE.finditer(fonte):
        nome, bases = match.group(1), match.group(2)
        if "ModelView" not in bases or nome == "MyModelView":
            continue
        if "MyModelView" in bases or "BrazilianDateFormatsMixin" in bases:
            continue
        ofensores.append(f"  admin.py:{fonte[: match.start()].count(chr(10)) + 1} class {nome}({bases})")
    assert not ofensores, (
        "View do admin fora do formato brasileiro: herde de MyModelView ou de "
        "BrazilianDateFormatsMixin.\n" + "\n".join(ofensores)
    )


def test_pagina_servida_entrega_o_script(client):
    """Prova no HTML servido, não só no template."""
    resposta = client.get("/login")
    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert SCRIPT_DATA in corpo
    assert SCRIPT_HORA in corpo


# --- a varredura não pode ser vacuosa ----------------------------------------

@pytest.mark.parametrize(
    "trecho, tem_campo_de_data",
    [
        ('<input type="date" name="x">', True),
        ("<input type=date>", True),
        ('<input type="datetime-local">', True),
        ('<input type="month" class="form-control">', True),
        ('{ type: "date", owner: "sim" }', True),
        ('<input type="text">', False),
        ('<input type="time">', False),
    ],
)
def test_regex_reconhece_campo_de_data(trecho, tem_campo_de_data):
    assert bool(CAMPO_DE_DATA_RE.search(trecho)) is tem_campo_de_data


@pytest.mark.parametrize(
    "trecho, ofensor",
    [
        ("d.toLocaleDateString()", True),
        ("d.toLocaleString()", True),
        ("new Intl.DateTimeFormat(undefined, {})", True),
        ("d.toLocaleDateString('en-US')", True),
        ("d.toLocaleDateString('pt-BR')", False),
        ("new Intl.DateTimeFormat('pt-BR')", False),
        ("valor.toLocaleString('pt-BR', { style: 'currency' })", False),
    ],
)
def test_regex_de_locale_so_pega_o_que_depende_do_navegador(trecho, ofensor):
    assert bool(SEM_LOCALE_RE.search(trecho)) is ofensor


@pytest.mark.parametrize(
    "trecho, ofensor",
    [
        ("const hoje = new Date().toISOString().slice(0, 10);", True),
        ("const hoje = new Date().toISOString().split('T')[0];", True),
        ("payload.quando = new Date().toISOString();", False),
        ("const hoje = window.PetDateBR.todayIso();", False),
        # Data já deslocada para o fuso local antes de serializar: correto.
        ("const local = new Date(d.getTime() - off); return local.toISOString().slice(0, 10);", False),
    ],
)
def test_regex_de_hoje_em_utc(trecho, ofensor):
    assert bool(HOJE_EM_UTC_RE.search(trecho)) is ofensor


def test_familia_de_templates_segue_extends_e_include():
    templates = {
        "layout.html": "<html>{% block c %}{% endblock %}</html>",
        "pagina.html": "{% extends 'layout.html' %}{% include 'parcial.html' %}",
        "parcial.html": '<input type="date">',
        "solta.html": "<html><input type=\"text\"></html>",
    }
    familia = _familia(templates)
    assert familia["layout.html"] == {"layout.html", "pagina.html", "parcial.html"}
    assert familia["solta.html"] == {"solta.html"}
