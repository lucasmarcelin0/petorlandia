"""Navegação de campo (modelo em JavaScript): sintético e sobre a malha real da cidade."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services import entomologia_atlas_malha as malha
from services import entomologia_atlas_search as search

ROOT = Path(__file__).resolve().parents[1]


def _node(*args):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js não está disponível')
    return subprocess.run([node, str(ROOT / 'tests' / 'test_atlas_nav_model.js'), *map(str, args)], cwd=ROOT,
                          capture_output=True, text=True, timeout=180, check=False)


def test_modelo_de_navegacao_sintetico():
    result = _node()
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('stride', [1, 2, 3])
def test_modelo_de_navegacao_na_malha_real(app, tmp_path, stride):
    with app.app_context():
        search.reset()
        index = json.loads(search.client_index(True)[0])
    streets = sorted((e for e in index['entries'] if e[5] == 2 and e[8]), key=lambda e: (e[6] * stride) % 0.0731 + e[7])
    step = max(1, len(streets) // 7)
    points = [{'lng': e[6], 'lat': e[7], 'name': e[2]} for e in streets[::step][:7]]
    fixture = tmp_path / 'real.json'
    fixture.write_text(json.dumps({'graph': json.loads(malha.street_network()[0]), 'points': points}), encoding='utf-8')
    result = _node(fixture)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'reais' in result.stdout
