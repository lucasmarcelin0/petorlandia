"""Reject tracked personal exports while permitting the integration source."""
import pytest

from scripts import check_sensitive_artifacts as guard


@pytest.mark.parametrize('path', [
    'output/betha-access-test/sample.json',
    'output/betha-access-test/preview.html',
    'output/betha-access-test/sample.csv',
    'output/betha-access-test/espelho.pdf',
    'OUTPUT\\BETHA-ACCESS-TEST\\preview.html',
    'instance/sfa_cadastro.json',
    'static/data/sfa_cadastro.json',
    'services/data/sfa_cadastro.json',
    'outputs/old_survey_2025.json',
])
def test_guard_rejects_private_export(path, monkeypatch, capsys):
    monkeypatch.setattr(guard, 'tracked_files', lambda: [path])
    assert guard.main() == 1
    assert path in capsys.readouterr().err


def test_guard_allows_source_helper_and_ignore_rule(monkeypatch, capsys):
    monkeypatch.setattr(guard, 'tracked_files', lambda: [
        'services/entomologia_cadastro.py',
        'scripts/import_sfa_cadastro.py',
        'static/js/sfa_cadastro.js',
        'tests/test_sfa_cadastro.py',
        'output/betha-access-test/.gitignore',
        'services/data/entomologia/snapshot.json',
    ])
    assert guard.main() == 0
    assert not capsys.readouterr().err
