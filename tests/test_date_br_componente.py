"""O componente de datas funciona mesmo com o navegador em inglês.

O bug original só aparece quando o navegador NÃO está em português: o
`<input type="date">` nativo mostra "mm/dd/yyyy". Por isso aqui o Chromium
sobe com `locale="en-US"` — se a correção depender do idioma do navegador,
estes testes falham.

`tests/test_date_br.js` cobre as conversões puras (roda no Node, é rápido);
este arquivo cobre o comportamento na tela. A varredura que garante que toda
página carrega o componente está em `tests/test_datas_formato_brasileiro.py`.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC = PROJECT_ROOT / "static"

PAGINA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<link rel="stylesheet" href="{bootstrap}"></head>
<body class="p-3">
<form id="formulario" method="post" action="about:blank">
  <label for="dia">Data</label>
  <input type="date" id="dia" name="data" class="form-control" value="2026-09-22" required>
  <div class="input-group">
    <span class="input-group-text">De</span>
    <input type="date" id="intervalo" name="de" class="form-control" min="2026-09-10" max="2026-09-30">
  </div>
  <input type="datetime-local" id="quando" name="quando" class="form-control" value="2026-09-22T14:30">
  <input type="month" id="mes" name="mes" class="form-control" value="2026-09">
  <button id="enviar">Enviar</button>
</form>
<script>
  window.mudancas = [];
  ['dia', 'intervalo', 'quando', 'mes'].forEach((id) => {{
    document.getElementById(id).addEventListener('change', (e) => {{
      window.mudancas.push(id + '=' + e.target.value);
    }});
  }});
</script>
<script src="{componente}" defer></script>
</body></html>
"""


def _pular_sem_navegador():
    pytest.importorskip("playwright", reason="playwright não instalado")
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            navegador.close()
    except Exception as erro:  # navegador não baixado neste ambiente
        pytest.skip(f"Chromium do Playwright indisponível: {erro}")


@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    """Página real, servida de file://, com o componente de verdade."""
    _pular_sem_navegador()
    from playwright.sync_api import sync_playwright

    destino = tmp_path_factory.mktemp("date_br") / "pagina.html"
    destino.write_text(
        PAGINA.format(
            bootstrap=(STATIC / "bootstrap.min.css").as_uri(),
            componente=(STATIC / "js" / "date_br.js").as_uri(),
        ),
        encoding="utf-8",
    )

    with sync_playwright() as p:
        navegador = p.chromium.launch(args=["--lang=en-US"])
        contexto = navegador.new_context(locale="en-US", timezone_id="America/Sao_Paulo")
        aba = contexto.new_page()
        erros: list[str] = []
        aba.on("pageerror", lambda e: erros.append(str(e)))
        aba.goto(destino.as_uri())
        aba.wait_for_function("window.PetDateBR && document.querySelectorAll('.date-br-input').length === 4")
        aba.erros = erros  # type: ignore[attr-defined]
        yield aba
        navegador.close()


def espelho(aba, campo_id):
    return aba.evaluate_handle(
        f"PetDateBR.proxyFor(document.getElementById('{campo_id}'))"
    ).as_element()


def valor_nativo(aba, campo_id):
    return aba.eval_on_selector(f"#{campo_id}", "el => el.value")


def digitar(aba, campo_id, texto, tecla_final="Tab"):
    alvo = espelho(aba, campo_id)
    alvo.click()
    aba.keyboard.press("Escape")
    aba.keyboard.press("Control+A")
    aba.keyboard.type(texto)
    if tecla_final:
        aba.keyboard.press(tecla_final)
    return alvo


def test_conversoes_passam_no_node():
    """Sem isto, os testes de tela provariam pouco sobre as conversões."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node não disponível para exercitar o componente")
    suite = PROJECT_ROOT / "tests" / "test_date_br.js"
    resultado = subprocess.run(
        [node, str(suite)], capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=60
    )
    assert resultado.returncode == 0, f"{resultado.stdout}\n{resultado.stderr}"


def test_campo_aparece_em_portugues_mesmo_com_navegador_em_ingles(pagina):
    """O caso do print: navegador em inglês mostrava mm/dd/yyyy."""
    textos = pagina.eval_on_selector_all(".date-br-input", "els => els.map(el => el.value)")
    assert textos == ["22/09/2026", "", "22/09/2026 14:30", "09/2026"]
    marcadores = pagina.eval_on_selector_all(".date-br-input", "els => els.map(el => el.placeholder)")
    assert marcadores == ["dd/mm/aaaa", "dd/mm/aaaa", "dd/mm/aaaa hh:mm", "mm/aaaa"]
    assert pagina.eval_on_selector("#dia", "el => getComputedStyle(el).display") == "none"


def test_rotulo_continua_ligado_ao_campo(pagina):
    """Clicar no rótulo tem de levar o cursor para o campo visível."""
    pagina.click("label[for='dia']")
    assert pagina.evaluate("document.activeElement === PetDateBR.proxyFor(document.getElementById('dia'))")


def test_digitar_preenche_o_valor_tecnico_em_iso(pagina):
    alvo = digitar(pagina, "intervalo", "15092026")
    assert alvo.input_value() == "15/09/2026"
    assert valor_nativo(pagina, "intervalo") == "2026-09-15"
    assert "intervalo=2026-09-15" in pagina.evaluate("window.mudancas")


def test_data_impossivel_e_recusada_com_motivo(pagina):
    alvo = digitar(pagina, "dia", "31022026")
    assert alvo.input_value() == "31/02/2026", "o texto digitado não pode sumir"
    assert valor_nativo(pagina, "dia") == "", "data impossível não pode virar 03/03"
    assert pagina.eval_on_selector("#dia", "el => el.validationMessage") == (
        "Dia inválido: fevereiro de 2026 tem 28 dias."
    )
    assert "is-invalid" in (alvo.get_attribute("class") or "")


def test_limite_de_data_avisa_em_portugues(pagina):
    digitar(pagina, "intervalo", "01092026")
    assert pagina.eval_on_selector("#intervalo", "el => el.validationMessage") == (
        "Escolha uma data a partir de 10/09/2026."
    )
    # O valor continua no campo, como faz o campo nativo fora do intervalo.
    assert valor_nativo(pagina, "intervalo") == "2026-09-01"


def test_valor_definido_por_script_aparece_formatado(pagina):
    pagina.eval_on_selector("#dia", "el => { el.value = '2025-01-05'; }")
    assert espelho(pagina, "dia").input_value() == "05/01/2025"


def test_formulario_envia_iso(pagina):
    digitar(pagina, "dia", "05102026")
    digitar(pagina, "intervalo", "20092026")
    dados = pagina.evaluate("Object.fromEntries(new FormData(document.getElementById('formulario')))")
    assert dados["data"] == "2026-10-05"
    assert dados["de"] == "2026-09-20"
    assert dados["quando"] == "2026-09-22T14:30"
    assert dados["mes"] == "2026-09"
    assert pagina.evaluate("document.getElementById('formulario').checkValidity()") is True


def test_calendario_abre_em_portugues(pagina):
    espelho(pagina, "dia").click()
    pagina.wait_for_selector(".flatpickr-calendar.open", timeout=10_000)
    semana = pagina.inner_text(".flatpickr-calendar.open .flatpickr-weekdays")
    assert "Seg" in semana and "Sáb" in semana
    pagina.click(".flatpickr-calendar.open .flatpickr-day:not(.prevMonthDay):not(.nextMonthDay) >> text='17'")
    assert espelho(pagina, "dia").input_value() == "17/10/2026"
    assert valor_nativo(pagina, "dia") == "2026-10-17"


def test_mes_tem_seletor_em_portugues(pagina):
    alvo = espelho(pagina, "mes")
    alvo.click()
    pagina.wait_for_selector(".flatpickr-calendar.open .flatpickr-monthSelect-month", timeout=10_000)
    pagina.click(".flatpickr-calendar.open .flatpickr-monthSelect-month >> text='Dez'")
    assert alvo.input_value() == "12/2026"
    assert valor_nativo(pagina, "mes") == "2026-12"


def test_data_e_hora_em_24h(pagina):
    alvo = digitar(pagina, "quando", "010120270905")
    assert alvo.input_value() == "01/01/2027 09:05"
    assert valor_nativo(pagina, "quando") == "2027-01-01T09:05"


def test_campo_criado_depois_tambem_e_tratado(pagina):
    """Modais e listas montadas por JavaScript não podem escapar."""
    pagina.evaluate(
        "document.body.insertAdjacentHTML('beforeend',"
        " '<div id=novo><input type=date id=depois value=2026-12-25></div>')"
    )
    pagina.wait_for_function("PetDateBR.proxyFor(document.getElementById('depois'))")
    assert pagina.evaluate("PetDateBR.proxyFor(document.getElementById('depois')).value") == "25/12/2026"


def test_clone_de_linha_nao_duplica_espelho(pagina):
    """Formulários que clonam linhas com cloneNode continuam corretos."""
    pagina.evaluate(
        "const copia = document.getElementById('novo').cloneNode(true);"
        "copia.id = 'novo2';"
        "copia.querySelector('input[type=date]').id = 'depois2';"
        "document.body.appendChild(copia);"
    )
    pagina.wait_for_function("document.querySelectorAll('#novo2 .date-br-input').length === 1")
    assert pagina.eval_on_selector_all("#novo2 .date-br-input", "els => els.map(el => el.value)") == ["25/12/2026"]


def test_reset_do_formulario_volta_ao_valor_inicial(pagina):
    pagina.evaluate("document.getElementById('formulario').reset()")
    pagina.wait_for_function("PetDateBR.proxyFor(document.getElementById('dia')).value === '22/09/2026'")
    assert valor_nativo(pagina, "dia") == "2026-09-22"


def test_sem_erros_de_javascript(pagina):
    assert pagina.erros == []
