"""Avisos do controle de frascos podem ser fechados no painel do aplicador.

O aviso fechado fica escondido neste aparelho enquanto o texto for o mesmo;
se a situacao mudar (outra sobra, outra data), o texto muda e o aviso volta.
"""

import json
import shutil
import subprocess
import textwrap

import pytest

from tests.test_pmo_doses_do_dia import TEMPLATE, extract_function


@pytest.fixture(scope="module")
def source():
    return TEMPLATE.read_text(encoding="utf-8")


def run_notices(source, steps):
    node = shutil.which("node")
    if not node:
        pytest.skip("node nao disponivel neste ambiente")
    script = textwrap.dedent(
        """
        const store = {};
        const localStorage = {
          getItem: (k) => (k in store ? store[k] : null),
          setItem: (k, v) => { store[k] = String(v); },
        };
        function fakeEl() {
          const classes = new Set(['d-none']);
          return {
            innerHTML: '', textContent: '',
            classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c) },
            get hidden() { return classes.has('d-none'); },
          };
        }
        const stockHintEl = fakeEl();
        const stockAlertsEl = fakeEl();
        const stockDismissedBtn = fakeEl();
        const STOCK_DISMISSED_KEY = 'pmo_stock_dismissed_notices';
        const STOCK_DISMISSED_TTL_MS = 60 * 24 * 60 * 60 * 1000;
        let lastStock = null;
        let showDismissedNotices = false;
        """
    )
    script += "\n".join(
        extract_function(source, name)
        for name in (
            "escapeHtml",
            "readDismissedNotices",
            "writeDismissedNotices",
            "noticeHtml",
            "renderStockNotices",
            "handleStockNoticeClick",
        )
    )
    script += textwrap.dedent(
        f"""
        let dismissedNotices = readDismissedNotices();
        const out = [];
        for (const step of {json.dumps(steps)}) {{
          if (step.reload) dismissedNotices = readDismissedNotices();
          if (step.toggle) showDismissedNotices = !showDismissedNotices;
          if (step.dismiss) {{
            lastStock = step.stock || lastStock;
            handleStockNoticeClick({{ target: {{ closest: (sel) =>
              sel === '[data-stock-dismiss]' ? {{ dataset: {{ stockDismiss: step.dismiss }} }} : null }} }});
          }}
          if (step.stock) {{ lastStock = step.stock; renderStockNotices(step.stock); }}
          out.push({{
            hint: stockHintEl.hidden ? '' : stockHintEl.innerHTML,
            alerts: stockAlertsEl.hidden ? '' : stockAlertsEl.innerHTML,
            hiddenButton: stockDismissedBtn.hidden ? '' : stockDismissedBtn.textContent,
          }});
        }}
        console.log(JSON.stringify(out));
        """
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


STOCK = {
    "planningHint": "29/10/2026 já começa com 8 dose(s) da sobra.",
    "alerts": ["4 dose(s) do frasco aberto em 20/10/2026 venceram — lance como perda."],
}


def test_avisos_tem_botao_de_fechar(source):
    assert 'id="pmo-stock-dismissed"' in source
    first = run_notices(source, [{"stock": STOCK}])[0]
    assert "data-stock-dismiss" in first["hint"]
    assert "data-stock-dismiss" in first["alerts"]


def test_aviso_fechado_continua_fechado_ao_recarregar(source):
    alert = STOCK["alerts"][0]
    steps = run_notices(
        source,
        [
            {"stock": STOCK},
            {"dismiss": alert, "stock": STOCK},
            {"reload": True, "stock": STOCK},
        ],
    )
    assert "venceram" in steps[0]["alerts"]
    assert steps[1]["alerts"] == ""
    assert steps[2]["alerts"] == ""
    # O outro aviso nao some junto, e da para reexibir o fechado.
    assert "sobra" in steps[2]["hint"]
    assert "1 aviso(s) fechado(s)" in steps[2]["hiddenButton"]


def test_aviso_com_texto_novo_volta_a_aparecer(source):
    novo = dict(STOCK, alerts=["2 dose(s) do frasco aberto em 27/10/2026 venceram."])
    steps = run_notices(
        source,
        [{"dismiss": STOCK["alerts"][0], "stock": STOCK}, {"stock": novo}],
    )
    assert "27/10/2026" in steps[1]["alerts"]


def test_avisos_fechados_podem_ser_reexibidos(source):
    steps = run_notices(
        source,
        [{"dismiss": STOCK["alerts"][0], "stock": STOCK}, {"toggle": True, "stock": STOCK}],
    )
    assert "venceram" in steps[1]["alerts"]
    assert "data-stock-restore" in steps[1]["alerts"]
