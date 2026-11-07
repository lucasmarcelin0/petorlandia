"""Mini app iReverse: protótipo de certificadora de créditos de logística reversa.

O protótipo é estático (sem banco, sem rotas novas): fica no cantinho secreto
/surpresa e guarda os dados só no navegador. Estes testes travam:

- o card no /surpresa e as três peças servidas sem cache prolongado (uma versão
  antiga aplicaria regras de dupla contagem desatualizadas);
- a página avisando que é protótipo sem validade legal;
- as regras do núcleo (unicidade da NF-e, balanço de massa na cadeia
  atacadista → recicladora, papéis separados, janela temporal, baixa única,
  livro-razão encadeado), rodando os cenários em Node.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEM_CACHE = "no-cache, no-store, must-revalidate"


def test_card_do_ireverse_no_cantinho_secreto(client):
    resposta = client.get("/surpresa")

    assert resposta.status_code == 200
    html = resposta.get_data(as_text=True)
    assert 'href="/surpresa/ireverse.html"' in html
    # Os mini apps que já existiam continuam no arcade.
    for anterior in ("/sim/", "/surpresa/desafio.html", "/surpresa/musica.html",
                     "/surpresa/estudio.html", "/surpresa/sala-a-dois.html"):
        assert anterior in html


@pytest.mark.parametrize("arquivo", ["ireverse.html", "ireverse-core.js", "ireverse-app.js"])
def test_pecas_do_prototipo_sao_servidas_sem_cache(client, arquivo):
    resposta = client.get(f"/surpresa/{arquivo}")

    assert resposta.status_code == 200
    assert resposta.headers["Cache-Control"] == SEM_CACHE


def test_pagina_se_apresenta_como_prototipo_sem_validade(client):
    html = client.get("/surpresa/ireverse.html").get_data(as_text=True)

    assert "Protótipo · sem validade legal" in html
    assert "PROTÓTIPO · SEM VALIDADE LEGAL" in html  # marca d'água do certificado
    assert 'src="/surpresa/ireverse-core.js?v=' in html
    assert 'src="/surpresa/ireverse-app.js?v=' in html
    # Nada de CDN de script: a CSP do site só libera os hosts conhecidos.
    assert "<script src=\"http" not in html


def test_regras_do_nucleo_em_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js não está disponível")
    result = subprocess.run([node, str(ROOT / "tests" / "test_ireverse_core.js")], cwd=ROOT,
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
