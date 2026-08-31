import re
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARTIAL = PROJECT_ROOT / "templates" / "sfa" / "_instrument_experience_lab.html"
SCRIPT = PROJECT_ROOT / "static" / "js" / "sfa_instrument_lab.js"
MODEL_TEST = PROJECT_ROOT / "tests" / "test_sfa_instrument_lab_model.js"


def test_instrument_lab_dom_contract_has_unique_ids():
    html = PARTIAL.read_text(encoding="utf-8")
    ids = re.findall(r'\bid="([^"]+)"', html)

    assert len(ids) == len(set(ids)), "O laboratorio contem IDs HTML duplicados."
    assert {
        "sfa-instrument-lab",
        "sfa-lab-form-host",
        "sfa-lab-funnel",
        "sfa-lab-kpis",
        "sfa-lab-signals",
        "sfa-lab-ai-review",
        "sfa-lab-ial",
        "sfa-lab-data-rows",
        "sfa-lab-decisions",
        "sfa-lab-ablation-result",
        "sfa-lab-precision",
        "sfa-lab-question-utility",
    }.issubset(ids)


def test_instrument_lab_clearly_identifies_the_safe_synthetic_sandbox():
    html = PARTIAL.read_text(encoding="utf-8")

    assert "antes de alterar os formulários reais" in html
    assert "nada é gravado e os formulários reais não são alterados" in html
    assert "Dados inteiramente sintéticos" in html
    assert "não estimam a realidade de Orlândia" in html


def test_instrument_lab_exposes_semantic_false_friend_and_one_health_scenarios():
    html = PARTIAL.read_text(encoding="utf-8")
    options = dict(re.findall(r'<option\s+value="([^"]+)">([^<]+)</option>', html))

    assert "semantic" in options
    assert "falsefriends" in options
    assert "onehealth" in options
    assert "Mesma exposição descrita de formas diferentes" in options["semantic"]
    assert "Termos parecidos, fontes diferentes" in options["falsefriends"]
    assert "One Health" in options["onehealth"]


def test_instrument_lab_frames_ai_as_assistive_and_human_reviewed():
    html = PARTIAL.read_text(encoding="utf-8")

    assert "IA assistiva, não diagnóstica" in html
    assert "Uma pessoa responsável precisa aceitar ou rejeitar cada vínculo" in html
    assert "Nenhuma sugestão confirma causa" in html
    assert "conta como decisão da Vigilância" in html


def test_instrument_lab_is_ephemeral_and_uses_explicit_synthetic_scenarios():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "const COHORT_SIZE = 100" in script
    assert "length: COHORT_SIZE" in script
    assert "`sfa-lab-${stageKey}-${item.id}`" in script
    assert "detectable" in script
    assert "sporadic" in script
    assert "attrition" in script
    assert "semantic" in script
    assert "falsefriends" in script
    assert "onehealth" in script
    assert "wilsonInterval" in script
    assert "buildSignals" in script
    assert "renderAblation" in script
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_instrument_lab_default_scenario_covers_priority_sentinel_signals():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "food:almoco-comunitario" in script
    assert "environment:lama-roedores-jardim" in script
    assert "animal:fazenda-santa-clara" in script
    assert "vector:mosquitos-jardim-boa-vista" in script
    assert "não diagnósticos" in script
    assert "a hipótese de leptospirose depende de avaliação epidemiológica e clínica" in script


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js nao esta disponivel")
def test_instrument_lab_javascript_parses():
    result = subprocess.run(
        [shutil.which("node"), "--check", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js nao esta disponivel")
def test_instrument_lab_synthetic_model_contract():
    result = subprocess.run(
        [shutil.which("node"), str(MODEL_TEST)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
