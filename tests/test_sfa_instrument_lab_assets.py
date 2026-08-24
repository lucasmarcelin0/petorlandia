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
        "sfa-lab-kpis",
        "sfa-lab-signals",
        "sfa-lab-data-rows",
        "sfa-lab-decisions",
        "sfa-lab-ablation-result",
        "sfa-lab-precision",
    }.issubset(ids)


def test_instrument_lab_is_ephemeral_and_uses_explicit_synthetic_scenarios():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "length: 50" in script
    assert "detectable" in script
    assert "sporadic" in script
    assert "attrition" in script
    assert "wilsonInterval" in script
    assert "buildSignals" in script
    assert "renderAblation" in script
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


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
