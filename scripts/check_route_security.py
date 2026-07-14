#!/usr/bin/env python3
from __future__ import annotations
import ast, os, re, subprocess
from pathlib import Path

ROUTE_DECORATOR_NAMES = {"route"}
CENTRAL_AUTH_PATTERNS = ("ensure_", "authorize_", "require_", "check_")
EXCEPTION_PATTERNS = (
    re.compile(r"^/healthz?$"), re.compile(r"^/health/check$"), re.compile(r"^/login/?$"),
    re.compile(r"^/oauth/token$"), re.compile(r"^/webhook/"),
    # Webhook do PACS Orthanc: público por design, validado por token compartilhado (ORTHANC_WEBHOOK_TOKEN)
    re.compile(r"^/api/integrations/orthanc/webhook$"),
)
SENSITIVE_HINTS = ("<int:", "/api/", "/animal/", "/consulta/", "/tutor/", "/clinica", "/fiscal", "/orcamento", "/prescricao", "/exame")
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, text=True, capture_output=True, check=True).stdout.strip()


def resolve_base_commit() -> str:
    refs = []
    if os.environ.get("GITHUB_BASE_REF"):
        refs.append(f"origin/{os.environ['GITHUB_BASE_REF']}")
    refs.extend(["origin/main", "origin/master", "HEAD~1"])
    for ref in refs:
        try:
            return run(["git", "merge-base", "HEAD", ref])
        except Exception:
            continue
    return run(["git", "rev-parse", "HEAD"])


def changed_python_files(base_commit: str) -> set[Path]:
    out = run(["git", "diff", "--name-only", f"{base_commit}..HEAD", "--", "*.py"])
    return {Path(p) for p in out.splitlines() if p}


def added_lines(path: Path, base: str) -> set[int]:
    out = run(["git", "diff", "-U0", f"{base}..HEAD", "--", str(path)])
    added = set()
    for line in out.splitlines():
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start = int(m.group(1)); length = int(m.group(2) or "1")
                added.update(range(start, start + length))
    return added


def main() -> int:
    base = resolve_base_commit()
    files = changed_python_files(base)
    if not files:
        print("No changed Python files.")
        return 0
    errors = []
    for path in sorted(files):
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        added = added_lines(path, base)
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            routes = []
            has_login = any(((isinstance((d.func if isinstance(d, ast.Call) else d), ast.Name) and (d.func if isinstance(d, ast.Call) else d).id == "login_required") or (isinstance((d.func if isinstance(d, ast.Call) else d), ast.Attribute) and (d.func if isinstance(d, ast.Call) else d).attr == "login_required")) for d in fn.decorator_list)
            has_auth = any(isinstance(n, ast.Call) and any(((isinstance(n.func, ast.Name) and n.func.id.startswith(p)) or (isinstance(n.func, ast.Attribute) and n.func.attr.startswith(p))) for p in CENTRAL_AUTH_PATTERNS) for n in ast.walk(fn))
            for d in fn.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ROUTE_DECORATOR_NAMES and d.args and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
                    route = d.args[0].value
                    methods = {"GET"}
                    for kw in d.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            methods = {e.value.upper() for e in kw.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)} or {"GET"}
                    routes.append((route, methods, d.lineno))
            if not routes or not any(l in added or fn.lineno in added for _, _, l in routes):
                continue
            for route, methods, lineno in routes:
                if any(p.search(route) for p in EXCEPTION_PATTERNS):
                    continue
                sensitive = any(h in route for h in SENSITIVE_HINTS) or bool(methods & MUTATING_METHODS)
                if not sensitive:
                    continue
                if not has_login:
                    errors.append(f"{path}:{lineno} rota sensível '{route}' sem @login_required")
                if not has_auth:
                    errors.append(f"{path}:{lineno} rota sensível '{route}' sem chamada de autorização central")
    if errors:
        print("Falha de compliance de segurança de rotas:\n" + "\n".join(f"- {e}" for e in errors))
        print("\nExceções permitidas: healthcheck, login e webhooks públicos com validação por assinatura.")
        return 1
    print("Route security static check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
