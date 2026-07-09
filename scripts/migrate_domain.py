"""Ferramenta da modularização: migra um conjunto de views do app.py para um blueprint.

Uso:
    python scripts/migrate_domain.py <blueprint_name> <arquivo_saida> <view1> <view2> ...
        [--routes <json>]   # rotas extras p/ views sem @app.route (shim lazy_view)

- Extrai as funções do app.py (com decorators) e as remove de lá.
- Converte decorators @app.route(...) em @bp.route(...).
- Para views sem @app.route, usa o mapeamento --routes (JSON: nome -> [[rule, methods], ...]).
- Resolve imports via pyflakes + análise do app.py e gera o header:
  * nomes importados no app.py → import replicado;
  * nomes PATCHED (monkeypatch de testes) → wrapper late-bound via módulo app;
  * nomes definidos no app.py → bloco "from app import (...)";
  * nomes de models não resolvidos → tentativa via "from models import ...".
- Emite o bloco de reexport para colar no app.py (stdout).
"""
from __future__ import annotations

import ast
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from pyflakes.api import check
from pyflakes.reporter import Reporter

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"

# Nomes que testes monkeypatcham no módulo app → precisam de late-binding.
PATCHED = {
    "_is_admin", "upload_to_s3", "mp_sdk", "_s3", "CheckoutForm",
    "is_veterinarian", "BUCKET", "ensure_clinic_access",
    "_sync_orcamento_payment_classification", "verify_mp_signature",
    "reverse_geocode_city", "_render_orcamento_history",
    "classify_transactions_for_month", "_run_whatsapp_batch_selenium",
    "_criar_preferencia_pagamento", "BUCKET_NAME",
}


def function_spans(src):
    tree = ast.parse(src)
    spans = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            spans[node.name] = (start, node.end_lineno)
    return spans


def convert_app_routes(chunk: str, extra_routes) -> str:
    """Converte @app.route → @bp.route; adiciona rotas extras do shim."""
    out = re.sub(r"^@app\.route\(", "@bp.route(", chunk, flags=re.M)
    if extra_routes:
        decorators = "".join(
            f"@bp.route({json.dumps(rule)}, methods={json.dumps(methods)})\n"
            for rule, methods in extra_routes
        )
        # insere acima do primeiro decorator/def
        out = decorators + out
    return out


def build_header(bp_name, body_path):
    buf = io.StringIO()
    check(Path(body_path).read_text(encoding="utf-8"), str(body_path), Reporter(buf, buf))
    undef = sorted({
        l.split("undefined name")[-1].strip().strip("'\"")
        for l in buf.getvalue().splitlines()
        if "undefined name" in l
    })

    src = APP.read_text(encoding="utf-8")
    tree = ast.parse(src)
    import_map, defined = {}, set()
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

    try:
        import models as _models
        model_names = set(dir(_models))
    except Exception:
        model_names = set()

    by_module, from_app, wrappers, missing = defaultdict(list), [], [], []
    for n in undef:
        if n == "app":
            continue  # tratado como current_app pelo chamador
        if n in PATCHED:
            wrappers.append(n)
        elif n in import_map:
            mod, orig = import_map[n]
            by_module[mod].append((orig, n))
        elif n in defined:
            from_app.append(n)
        elif n in model_names:
            by_module["models"].append((n, n))
        else:
            missing.append(n)

    lines = [f'"""Views do domínio {bp_name} (migrado do app.py)."""']
    lines.append("from flask import Blueprint")
    for mod in sorted(by_module):
        pairs = sorted(set(by_module[mod]))
        names = ", ".join(o if o == a else f"{o} as {a}" for o, a in pairs)
        if mod == "__import__":
            lines.append(f"import {names}")
        else:
            lines.append(f"from {mod} import {names}")
    if from_app:
        lines.append("")
        lines.append("# Helpers ainda hospedados no app.py (realocação em fases futuras).")
        lines.append("from app import (  # noqa: E402")
        for n in sorted(from_app):
            lines.append(f"    {n},")
        lines.append(")")
    lines.append("")
    lines.append(f'bp = Blueprint("{bp_name}", __name__)')
    lines.append("")
    lines.append("")
    lines.append("def get_blueprint():")
    lines.append("    return bp")
    lines.append("")
    for n in sorted(wrappers):
        lines.append("")
        lines.append(f"def {n}(*args, **kwargs):")
        lines.append("    # Late-binding: testes fazem monkeypatch de app.%s." % n)
        lines.append("    import app as app_module")
        lines.append(f"    return app_module.{n}(*args, **kwargs)")
        lines.append("")
    if missing:
        lines.append("")
        lines.append(f"# TODO resolver manualmente: {missing}")
    lines.append("")
    lines.append("")
    return "\n".join(lines), missing


def main():
    args = sys.argv[1:]
    routes_extra = {}
    if "--routes" in args:
        i = args.index("--routes")
        routes_extra = json.loads(args[i + 1])
        del args[i:i + 2]
    bp_name, out_path, *names = args

    src = APP.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    spans = function_spans(src)
    missing_fn = [n for n in names if n not in spans]
    if missing_fn:
        print(f"NAO ENCONTRADAS: {missing_fn}")
        sys.exit(1)

    ordered = sorted(names, key=lambda n: spans[n][0])
    chunks = []
    for name in ordered:
        s, e = spans[name]
        chunk = "".join(lines[s - 1:e])
        chunks.append(convert_app_routes(chunk, routes_extra.get(name)))

    body = "\n\n".join(chunks) + "\n"
    tmp = Path(out_path)
    tmp.write_text(body, encoding="utf-8")

    # remove do app.py
    for name in sorted(ordered, key=lambda n: spans[n][0], reverse=True):
        s, e = spans[name]
        del lines[s - 1:e]
    APP.write_text("".join(lines), encoding="utf-8")

    header, missing = build_header(bp_name, tmp)
    tmp.write_text(header + body, encoding="utf-8")

    print(f"OK: {len(ordered)} views -> {out_path}; app.py atualizado")
    if missing:
        print(f"MISSING (resolver na mao): {missing}")
    print("\n# Reexport para app.py:")
    print(f"from {out_path.replace('/', '.').removesuffix('.py')} import (  # noqa: E402,F401")
    for n in sorted(ordered):
        print(f"    {n},")
    print(")")


if __name__ == "__main__":
    main()
