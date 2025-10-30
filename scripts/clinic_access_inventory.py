"""Audit login-protected routes for clinic access enforcement."""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "app.py"


@dataclass
class RouteInfo:
    function_name: str
    routes: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    ensure_calls: bool = False
    decorators: List[str] = field(default_factory=list)
    lineno: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "function": self.function_name,
            "routes": self.routes,
            "methods": self.methods,
            "ensure_clinic_access": self.ensure_calls,
            "decorators": self.decorators,
            "lineno": self.lineno,
        }


class RouteVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.routes: list[RouteInfo] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:  # type: ignore[override]
        decorators = [self._decorator_name(d) for d in node.decorator_list]
        if not any(name.endswith("login_required") for name in decorators if name):
            # Skip routes that are not authenticated
            return

        route_paths: list[str] = []
        methods: list[str] = []
        for decorator in node.decorator_list:
            route_info = self._extract_route(decorator)
            if route_info:
                route_paths.extend(route_info[0])
                methods.extend(route_info[1])

        ensure_calls = self._has_ensure_call(node)

        self.routes.append(
            RouteInfo(
                function_name=node.name,
                routes=sorted(set(route_paths)),
                methods=sorted(set(methods)),
                ensure_calls=ensure_calls,
                decorators=[d for d in decorators if d],
                lineno=node.lineno,
            )
        )

    def _has_ensure_call(self, node: ast.FunctionDef) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Name) and func.id == "ensure_clinic_access":
                    return True
                if isinstance(func, ast.Attribute) and func.attr == "ensure_clinic_access":
                    return True
        return False

    def _decorator_name(self, decorator: ast.expr) -> str | None:
        if isinstance(decorator, ast.Name):
            return decorator.id
        if isinstance(decorator, ast.Attribute):
            value = self._decorator_name(decorator.value) or ""
            if value:
                return f"{value}.{decorator.attr}"
            return decorator.attr
        if isinstance(decorator, ast.Call):
            return self._decorator_name(decorator.func)
        return None

    def _extract_route(self, decorator: ast.expr) -> Optional[tuple[list[str], list[str]]]:
        if not isinstance(decorator, ast.Call):
            return None
        func_name = self._decorator_name(decorator.func) or ""
        if not func_name.endswith("route"):
            return None

        paths: list[str] = []
        methods: list[str] = []

        for arg in decorator.args:
            value = self._literal_value(arg)
            if isinstance(value, str):
                paths.append(value)
            elif isinstance(value, Iterable):
                for item in value:
                    if isinstance(item, str):
                        paths.append(item)

        for keyword in decorator.keywords:
            if keyword.arg == "rule":
                value = self._literal_value(keyword.value)
                if isinstance(value, str):
                    paths.append(value)
            elif keyword.arg == "methods":
                value = self._literal_value(keyword.value)
                if isinstance(value, Iterable):
                    for item in value:
                        if isinstance(item, str):
                            methods.append(item)

        return paths, methods

    def _literal_value(self, node: ast.AST) -> Any:
        try:
            return ast.literal_eval(node)
        except Exception:  # noqa: BLE001
            if isinstance(node, ast.List):
                result = []
                for elt in node.elts:
                    value = self._literal_value(elt)
                    result.append(value)
                return result
            if isinstance(node, ast.Tuple):
                return tuple(self._literal_value(elt) for elt in node.elts)
            return None


def collect_routes() -> list[RouteInfo]:
    source = APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    visitor = RouteVisitor()
    visitor.visit(tree)
    return visitor.routes


def main() -> None:
    routes = collect_routes()
    routes.sort(key=lambda info: info.lineno)
    data = [route.to_dict() for route in routes]
    output_path = REPO_ROOT / "docs" / "clinic_access_inventory.json"
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
