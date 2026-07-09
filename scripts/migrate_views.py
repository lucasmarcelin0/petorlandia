"""Ferramenta da modularização: extrai views do app.py para um blueprint.

Uso:
    python scripts/migrate_views.py extract <nome1> <nome2> ... --out <arquivo>
        Extrai as funções (com decorators) do app.py, grava o código bruto em
        <arquivo> e substitui o primeiro bloco removido por um reexport de
        compatibilidade (from blueprints.X import ...) — o texto do reexport é
        gravado em <arquivo>.reexport para ajuste manual.

    python scripts/migrate_views.py undefined <blueprint.py>
        Roda pyflakes e lista os nomes indefinidos (para montar os imports).

O ajuste fino (imports do blueprint, decorators @bp.route) é manual.
"""
from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app.py"


def _function_spans(src: str):
    """Map nome -> (start_line, end_line) incluindo decorators, 1-based inclusive."""
    tree = ast.parse(src)
    spans = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            spans[node.name] = (start, node.end_lineno)
    return spans


def extract(names, out_path):
    src = APP.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    spans = _function_spans(src)

    missing = [n for n in names if n not in spans]
    if missing:
        print(f"NAO ENCONTRADAS no app.py: {missing}")
        sys.exit(1)

    ordered = sorted(names, key=lambda n: spans[n][0])
    chunks = []
    for name in ordered:
        start, end = spans[name]
        chunks.append("".join(lines[start - 1:end]))

    Path(out_path).write_text("\n\n".join(chunks) + "\n", encoding="utf-8")

    # Remove do app.py (de trás para frente para não deslocar índices)
    for name in sorted(ordered, key=lambda n: spans[n][0], reverse=True):
        start, end = spans[name]
        del lines[start - 1:end]

    APP.write_text("".join(lines), encoding="utf-8")

    reexport = (
        "from blueprints.MODULE import (  # noqa: E402,F401\n"
        + "".join(f"    {n},\n" for n in sorted(ordered))
        + ")\n"
    )
    Path(str(out_path) + ".reexport").write_text(reexport, encoding="utf-8")
    print(f"extraidas {len(ordered)} funcoes -> {out_path}")
    print("app.py atualizado (blocos removidos). Reexport sugerido em .reexport")


def undefined(path):
    from pyflakes.api import check
    from pyflakes.reporter import Reporter

    buf = io.StringIO()
    check(Path(path).read_text(encoding="utf-8"), str(path), Reporter(buf, buf))
    names = set()
    for line in buf.getvalue().splitlines():
        if "undefined name" in line:
            names.add(line.split("undefined name")[-1].strip().strip("'\""))
    for n in sorted(names):
        print(n)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "extract":
        args = sys.argv[2:]
        out_idx = args.index("--out")
        names = args[:out_idx]
        extract(names, args[out_idx + 1])
    elif cmd == "undefined":
        undefined(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)
