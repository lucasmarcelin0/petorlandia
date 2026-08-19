"""
preflight_deploy.py
===================
Checagens que reproduzem localmente o que o Heroku faz no release phase, para
que a falha apareca aqui em segundos em vez de aparecer la, no meio do deploy,
com o dyno velho ainda de pe e o novo recusando subir.

O Procfile roda ``release: flask db upgrade``. Toda falha desse comando aborta
o release inteiro. As checagens:

  heads     Duas migrations com o mesmo down_revision criam duas cabecas e o
            ``flask db upgrade`` para com "Multiple head revisions are
            present". E o modo mais comum de quebrar o deploy, porque acontece
            sozinho sempre que duas branches criam migration em paralelo.

  chain     Toda migration carrega e tem down_revision que resolve. Pega erro
            de sintaxe, revision id repetido e referencia para migration que
            foi apagada.

  pending   Mostra exatamente quais migrations o release vai aplicar. Opcional:
            so roda com PREFLIGHT_DATABASE_URL apontando para uma COPIA do
            banco de producao (nunca para a producao).

  imports   ``create_app()`` funciona. Se nao, o release passa e o web dyno
            morre em loop no boot -- o pior caso, porque o deploy "deu certo".

  procfile  release e web continuam declarados.

Por que nao existe uma checagem que aplica tudo num banco vazio: o historico
deste repositorio nao e replayavel do zero (a migration inicial ja assume
tabelas anteriores ao Alembic). O banco de producao foi construido
incrementalmente; usar ``pending`` contra uma copia restaurada e o equivalente
honesto.

Uso:
  python scripts/preflight_deploy.py              # tudo
  python scripts/preflight_deploy.py --check heads
  python scripts/preflight_deploy.py --quiet      # so o resumo

Codigo de saida 0 = pode publicar. Qualquer outro = nao publique.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def _supports_color() -> bool:
    return sys.stdout.isatty() and os.name != "nt" or bool(os.environ.get("FORCE_COLOR"))


def _paint(text: str, color: str) -> str:
    return f"{color}{text}{RESET}" if _supports_color() else text


class CheckResult:
    def __init__(self, name: str, ok: bool, detail: str = "", fix: str = ""):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.fix = fix


def check_heads() -> CheckResult:
    """Uma unica cabeca no historico do Alembic."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(REPO_ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    if len(heads) == 1:
        return CheckResult("heads", True, f"cabeca unica: {heads[0]}")

    detail_lines = [f"{len(heads)} cabecas: {', '.join(heads)}"]
    for head in heads:
        revision = script.get_revision(head)
        detail_lines.append(
            f"  {head}  <- {revision.down_revision}  ({revision.doc or 'sem descricao'})"
        )
    newest = heads[-1]
    return CheckResult(
        "heads",
        False,
        "\n".join(detail_lines),
        fix=(
            "Escolha qual migration vem depois e aponte o down_revision dela\n"
            f"     para a outra cabeca (ex.: down_revision = '{newest}').\n"
            "     Alternativa: flask db merge heads -m 'merge'"
        ),
    )


def check_chain() -> CheckResult:
    """Toda migration importa e tem down_revision que resolve, sem duplicatas.

    Nao tentamos aplicar a cadeia desde zero: o historico deste repositorio nao
    e replayavel num banco vazio (a migration inicial ja assume tabelas que
    vieram de antes do Alembic). O banco de producao foi construido
    incrementalmente, e o que o release phase faz e aplicar apenas o que falta.
    O que da para garantir aqui -- e o que de fato quebra o release -- e que os
    arquivos carregam e que o grafo esta integro.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(REPO_ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))

    try:
        script = ScriptDirectory.from_config(config)
        revisions = list(script.walk_revisions())
    except Exception as exc:
        return CheckResult(
            "chain",
            False,
            f"nao foi possivel carregar as migrations: {type(exc).__name__}: {exc}",
            fix="Erro de sintaxe ou revision id repetido em migrations/versions/.",
        )

    known = {revision.revision for revision in revisions}
    problems: list[str] = []
    for revision in revisions:
        downs = revision.down_revision
        if downs is None:
            continue
        for down in (downs if isinstance(downs, tuple) else (downs,)):
            if down not in known:
                problems.append(
                    f"{revision.revision} aponta para {down}, que nao existe"
                )

    if problems:
        return CheckResult(
            "chain",
            False,
            "\n".join(problems),
            fix="Corrija o down_revision ou restaure a migration que sumiu.",
        )
    return CheckResult("chain", True, f"{len(revisions)} migrations, grafo integro")


def check_pending() -> CheckResult:
    """Compara a revisao aplicada no banco real com a cabeca do repositorio.

    So roda quando ``PREFLIGHT_DATABASE_URL`` esta definida -- aponte para uma
    copia restaurada do banco de producao (nunca para a producao em si). E a
    unica forma honesta de saber o que o release phase vai executar.
    """
    url = os.environ.get("PREFLIGHT_DATABASE_URL", "").strip()
    if not url:
        return CheckResult(
            "pending",
            True,
            "pulado (defina PREFLIGHT_DATABASE_URL para checar contra um banco real)",
        )

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    config = Config(str(REPO_ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    except Exception as exc:
        return CheckResult("pending", False, f"{type(exc).__name__}: {exc}")
    finally:
        engine.dispose()

    head = script.get_current_head()
    if current == head:
        return CheckResult("pending", True, f"banco ja esta em {head}: nada a aplicar")

    try:
        pending = [
            revision.revision
            for revision in script.iterate_revisions(head, current)
        ]
    except Exception as exc:
        return CheckResult(
            "pending",
            False,
            f"o banco esta em {current}, fora da cadeia atual: {exc}",
            fix="O banco tem revisao que este repositorio nao conhece.",
        )

    return CheckResult(
        "pending",
        True,
        f"{len(pending)} migration(s) serao aplicadas no release: "
        + ", ".join(reversed(pending)),
    )


def check_imports() -> CheckResult:
    """A aplicacao importa e monta -- o que o gunicorn vai fazer no boot."""
    try:
        from app_factory import create_app

        app = create_app()
        rules = len(list(app.url_map.iter_rules()))
    except Exception as exc:
        return CheckResult(
            "imports",
            False,
            f"{type(exc).__name__}: {exc}",
            fix="O web dyno nao sobe assim. Rode com --verbose para o traceback.",
        )
    return CheckResult("imports", True, f"create_app() ok, {rules} rotas registradas")


def check_procfile() -> CheckResult:
    """O Procfile existe e declara os processos esperados."""
    procfile = REPO_ROOT / "Procfile"
    if not procfile.exists():
        return CheckResult("procfile", False, "Procfile nao encontrado")

    content = procfile.read_text(encoding="utf-8")
    missing = [name for name in ("release:", "web:") if name not in content]
    if missing:
        return CheckResult(
            "procfile",
            False,
            f"faltando no Procfile: {', '.join(missing)}",
        )
    return CheckResult("procfile", True, "release e web declarados")


CHECKS = {
    "heads": check_heads,
    "chain": check_chain,
    "pending": check_pending,
    "imports": check_imports,
    "procfile": check_procfile,
}

# heads primeiro: e a falha mais comum e a mais barata de detectar.
CHECK_ORDER = ["heads", "chain", "pending", "imports", "procfile"]


def run(selected: list[str] | None = None, quiet: bool = False, verbose: bool = False) -> int:
    names = selected or CHECK_ORDER
    results: list[CheckResult] = []

    for name in names:
        check = CHECKS[name]
        if not quiet:
            print(f"  {name} ...", end=" ", flush=True)
        try:
            result = check()
        except Exception as exc:
            if verbose:
                traceback.print_exc()
            result = CheckResult(name, False, f"{type(exc).__name__}: {exc}")
        results.append(result)
        if not quiet:
            print(_paint("ok", GREEN) if result.ok else _paint("FALHOU", RED))
            if result.detail:
                for line in result.detail.splitlines():
                    print(f"     {line}")

    failed = [result for result in results if not result.ok]
    print()
    if not failed:
        print(_paint(f"Preflight ok ({len(results)} checagens). Pode publicar.", GREEN))
        return 0

    print(_paint(f"Preflight reprovou em {len(failed)} de {len(results)}:", RED))
    for result in failed:
        print(f"\n  {_paint(result.name, RED)}")
        for line in result.detail.splitlines():
            print(f"     {line}")
        if result.fix:
            print(f"     {_paint('como resolver:', YELLOW)} {result.fix}")
    print()
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="append",
        choices=sorted(CHECKS),
        help="Roda apenas a checagem indicada (pode repetir).",
    )
    parser.add_argument("--quiet", action="store_true", help="So o resumo final.")
    parser.add_argument("--verbose", action="store_true", help="Traceback completo nas falhas.")
    args = parser.parse_args()

    # A checagem 'imports' monta a aplicacao. Aponta o banco para um arquivo
    # descartavel antes de qualquer import: o config.py le DATABASE_URL na
    # definicao da classe, e nenhuma checagem deve tocar o banco de dev.
    # ignore_cleanup_errors porque no Windows o SQLite segura o arquivo ate o
    # interpretador encerrar.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        os.environ["DATABASE_URL"] = f"sqlite:///{(Path(tmpdir) / 'preflight.db').as_posix()}"
        os.environ.pop("SQLALCHEMY_DATABASE_URI", None)
        return run(selected=args.check, quiet=args.quiet, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
