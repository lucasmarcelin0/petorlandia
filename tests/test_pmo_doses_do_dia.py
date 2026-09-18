"""Contagem de doses do dia no painel de vacinacao.

A casa pode ser reinscrita na planilha depois de ja ter sido atendida. Quando
isso acontece, os animais com dose valida do ano nao podem entrar de novo na
conta de doses previstas: o vacinador precisa ver quantos realmente faltam.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "vacina_pmo" / "dashboard.html"


@pytest.fixture(scope="module")
def source():
    return TEMPLATE.read_text(encoding="utf-8")


def extract_function(source, name):
    match = re.search(
        rf"\n  function {re.escape(name)}\([^)]*\)\s*\{{.*?\n  \}}\n",
        source,
        re.S,
    )
    assert match, f"funcao {name} nao encontrada"
    return textwrap.dedent(match.group(0))


def run_progress(source, animals):
    node = shutil.which("node")
    if not node:
        pytest.skip("node nao disponivel neste ambiente")
    script = "\n".join(
        [
            extract_function(source, "animalAwaitsDose"),
            extract_function(source, "vaccinationProgress"),
            f"const row = {{ animals: {json.dumps(animals)} }};",
            "console.log(JSON.stringify(vaccinationProgress(row)));",
        ]
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def vacinado_ontem(status="pendente"):
    return {
        "status": status,
        "previousVaccination": {
            "immune": True,
            "match": "exato",
            "dateLabel": "16/09/2026",
            "protectedUntilLabel": "16/09/2027",
        },
    }


def test_animais_vacinados_no_ano_nao_entram_nas_doses_do_dia(source):
    animals = [vacinado_ontem() for _ in range(6)] + [
        {"status": "pendente", "previousVaccination": None},
        {"status": "pendente", "previousVaccination": None},
    ]
    progress = run_progress(source, animals)
    assert progress["total"] == 2
    assert progress["done"] == 0
    assert progress["protected"] == 6


def test_dose_aplicada_hoje_conta_mesmo_em_animal_ja_protegido(source):
    progress = run_progress(source, [vacinado_ontem("vacinado"), vacinado_ontem()])
    assert progress["total"] == 1
    assert progress["done"] == 1
    assert progress["pct"] == 100


def test_ja_imunizado_sai_da_fila(source):
    progress = run_progress(
        source,
        [
            {"status": "imunizado", "previousVaccination": None},
            {"status": "pendente", "previousVaccination": None},
        ],
    )
    assert progress["total"] == 1
    assert progress["protected"] == 1


def test_correspondencia_aproximada_continua_na_fila(source):
    animal = vacinado_ontem()
    animal["previousVaccination"]["match"] = "aproximado"
    progress = run_progress(source, [animal])
    assert progress["total"] == 1
    assert progress["protected"] == 0


def test_dose_vencida_continua_na_fila(source):
    animal = vacinado_ontem()
    animal["previousVaccination"]["immune"] = False
    progress = run_progress(source, [animal])
    assert progress["total"] == 1


def test_aviso_de_imunidade_quebra_linha_dentro_da_coluna(source):
    assert 'class="pmo-animal-immunity__text"' in source
    assert ".pmo-animal-immunity__text {" in source
    # Um texto por caso previsto: ja imunizado sem data, ja imunizado com data,
    # conferencia por nome parecido, dose valida e dose vencida.
    assert source.count('class="pmo-animal-immunity__text"') == 5


def test_aviso_de_imunidade_ocupa_a_linha_inteira(source):
    """Preso na coluna do nome, o texto saia por cima do seletor de status."""
    assert ".pmo-animal-item > .pmo-animal-immunity {" in source
    assert "grid-column: 1 / -1;" in source


def test_data_do_aviso_nao_quebra_no_meio(source):
    assert ".pmo-animal-immunity__date {" in source
    assert 'class="pmo-animal-immunity__date"' in source
