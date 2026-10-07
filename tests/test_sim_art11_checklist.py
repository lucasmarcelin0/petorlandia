"""Checklist do art. 11 da LC 84/2024 no Portal SIM: lista da lei x semente x tela."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from blueprints.sim import SEED_STATE

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "static" / "sim_portal" / "app.js").read_text(encoding="utf-8")
INCISOS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


def _art11_items():
    block = APP_JS[APP_JS.index("const ART11_ITEMS = ["):APP_JS.index("const ART11_BY_DOCUMENT")]
    return re.findall(r'\{ inciso: "([IVX]+)", documentId: "([a-z0-9-]+)"', block)


def test_painel_lista_os_doze_incisos_na_ordem_da_lei():
    assert [inciso for inciso, _ in _art11_items()] == INCISOS


def test_cada_inciso_aponta_para_o_item_correspondente_da_semente():
    seed = [doc for doc in SEED_STATE["documents"] if doc.get("group") == "art11"]
    # A semente numera os itens de 01 a 12 na ordem dos incisos; um documento
    # do art. 11 sem inciso (ou o contrario) some do painel sem aviso.
    assert [(INCISOS[int(doc["item"]) - 1], doc["id"]) for doc in seed] == _art11_items()


def test_fonte_legal_do_cartao_cita_o_mesmo_inciso_do_painel():
    for inciso, document_id in _art11_items():
        sources = re.search(rf'"{document_id}": \[(.*?)\],\n', APP_JS, flags=re.S)
        assert sources, f"{document_id} sem fonte legal em DOCUMENT_SOURCES"
        assert re.search(rf'LC 84/2024, art\. 11, {inciso}\b', sources.group(1)), (
            f"{document_id}: a fonte legal do cartao nao cita o inciso {inciso}"
        )


def test_situacao_e_pendencias_do_art_11():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js não está disponível")
    result = subprocess.run([node, str(ROOT / "tests" / "test_sim_art11_model.js")], cwd=ROOT,
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
