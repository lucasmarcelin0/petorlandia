"""Invariantes das migrations que o release phase do Heroku exige.

O Procfile roda ``release: flask db upgrade``. Se o historico do Alembic tiver
duas cabecas, esse comando para com "Multiple head revisions are present" e o
deploy inteiro aborta -- com o dyno antigo de pe e o novo recusando subir.

A bifurcacao nao vem de erro de digitacao: acontece sozinha sempre que duas
branches criam migration a partir da mesma revisao. Por isso a checagem mora
aqui, na suite, e nao so no script de deploy: qualquer merge que reintroduza o
problema falha antes de chegar no push.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def script_directory() -> ScriptDirectory:
    config = Config(str(REPO_ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return ScriptDirectory.from_config(config)


def test_migrations_have_a_single_head(script_directory):
    heads = script_directory.get_heads()

    assert len(heads) == 1, (
        "O historico do Alembic bifurcou e 'flask db upgrade' vai falhar no "
        f"release do Heroku. Cabecas: {heads}. Aponte o down_revision da "
        "migration mais nova para a outra cabeca (ou use 'flask db merge heads')."
    )


def test_every_migration_resolves_its_parent(script_directory):
    revisions = list(script_directory.walk_revisions())
    known = {revision.revision for revision in revisions}

    dangling = []
    for revision in revisions:
        downs = revision.down_revision
        if downs is None:
            continue
        for down in (downs if isinstance(downs, tuple) else (downs,)):
            if down not in known:
                dangling.append(f"{revision.revision} -> {down}")

    assert not dangling, (
        "Migrations apontando para revisoes que nao existem: "
        f"{dangling}. O upgrade para na primeira delas."
    )


def test_revision_identifiers_are_unique(script_directory):
    revisions = [revision.revision for revision in script_directory.walk_revisions()]

    duplicates = {rev for rev in revisions if revisions.count(rev) > 1}

    assert not duplicates, f"Revision ids repetidos: {duplicates}"
