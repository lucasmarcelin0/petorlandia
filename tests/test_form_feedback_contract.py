from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_async_form_feedback_contract_in_browser_runtime():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js não está disponível para validar o contrato do navegador")

    result = subprocess.run(
        [node, str(PROJECT_ROOT / "tests" / "test_form_feedback_contract.js")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr

