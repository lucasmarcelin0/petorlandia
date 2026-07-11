"""Fail CI when known raw user exports are reintroduced into the repository.

Presentation material may contain only aggregate, anonymized metrics. Raw
survey/database exports must stay outside Git and outside public artifacts.
"""

from __future__ import annotations

import subprocess
import sys


FORBIDDEN_PATH_FRAGMENTS = (
    "db_presentation_data_2026.json",
    "dados_unificados_mercado_racao.csv",
    "old_survey_2025.json",
    "old_survey_2025.csv",
)


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [path.decode("utf-8", "replace") for path in result.stdout.split(b"\0") if path]


def main() -> int:
    violations = [
        path
        for path in tracked_files()
        if any(fragment in path for fragment in FORBIDDEN_PATH_FRAGMENTS)
    ]
    if violations:
        print("Arquivos sensíveis rastreados no Git:", file=sys.stderr)
        for path in violations:
            print(f" - {path}", file=sys.stderr)
        print(
            "Remova exports brutos; use apenas dados agregados e anonimizados.",
            file=sys.stderr,
        )
        return 1
    print("Nenhum export bruto conhecido está rastreado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
