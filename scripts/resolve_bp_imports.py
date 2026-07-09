"""Ferramenta da modularização: sugere imports para um blueprint extraído.

Uso: python scripts/resolve_bp_imports.py <arquivo.py>

Para cada nome indefinido (pyflakes), procura a origem no app.py:
- importado lá → replica o import agrupado por módulo;
- definido lá (def/class/atribuição) → lista em FROM APP;
- caso contrário → MISSING (resolver manualmente, ex.: models).
"""
from __future__ import annotations

import ast
import io
import sys
from collections import defaultdict
from pathlib import Path

from pyflakes.api import check
from pyflakes.reporter import Reporter

APP = Path(__file__).resolve().parents[1] / "app.py"


def main(path):
    buf = io.StringIO()
    check(Path(path).read_text(encoding="utf-8"), str(path), Reporter(buf, buf))
    undef = sorted({
        l.split("undefined name")[-1].strip().strip("'\"")
        for l in buf.getvalue().splitlines()
        if "undefined name" in l
    })

    src = APP.read_text(encoding="utf-8")
    tree = ast.parse(src)
    import_map = {}
    defined = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for a in node.names:
                import_map[a.asname or a.name] = (node.module, a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                import_map[a.asname or a.name.split(".")[0]] = ("__import__", a.name)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    defined.add(t.id)

    by_module = defaultdict(list)
    from_app, missing = [], []
    for n in undef:
        if n in import_map:
            mod, orig = import_map[n]
            by_module[mod].append((orig, n))
        elif n in defined:
            from_app.append(n)
        else:
            missing.append(n)

    for mod in sorted(by_module):
        names = ", ".join(o if o == a else f"{o} as {a}" for o, a in sorted(by_module[mod]))
        print(f"import {names}" if mod == "__import__" else f"from {mod} import {names}")
    print("\nFROM APP:", ", ".join(sorted(from_app)))
    print("\nMISSING:", missing)


if __name__ == "__main__":
    main(sys.argv[1])
