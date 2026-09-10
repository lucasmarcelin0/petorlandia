"""Roda a suíte JS do Apps Script da planilha de vacinação.

O script vive dentro do Google Sheets e não é importável pelo app, mas é ele
que monta o link do mapa, a mensagem de WhatsApp e a ordem das linhas da aba
mestre — e foi um erro de coluna nele que colocou o nome do tutor no lugar da
rua. A suíte em ``tests/test_apps_script_vacinacao.js`` exercita o arquivo de
verdade contra stubs de ``SpreadsheetApp``.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "apps_script" / "vacinacao_2026.gs"
SUITE = PROJECT_ROOT / "tests" / "test_apps_script_vacinacao.js"


def test_arquivo_do_apps_script_existe():
    """A cópia versionada é o que impede a correção de se perder na planilha."""
    assert SCRIPT.is_file()


def test_token_nao_fica_escrito_no_codigo():
    conteudo = SCRIPT.read_text(encoding="utf-8")
    assert "PropertiesService.getScriptProperties" in conteudo
    assert "X-PMO-Token': '" not in conteudo


def test_suite_js_passa():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node não disponível para exercitar o Apps Script")

    assert SUITE.is_file(), "suíte JS do Apps Script não encontrada"

    resultado = subprocess.run(
        [node, str(SUITE)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=120,
    )
    assert resultado.returncode == 0, (
        f"suíte JS do Apps Script falhou:\n{resultado.stdout}\n{resultado.stderr}"
    )
