"""Executa regressões dos controles de posologia sem acessar banco externo."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_posologia_estruturada_runtime():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js necessário para testar os seletores de posologia')
    result = subprocess.run(
        [node, '--test', str(Path(__file__).with_suffix('.js'))],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
