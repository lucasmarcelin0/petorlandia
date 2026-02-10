from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Set

from flask import url_for


EXCLUDED_ENDPOINTS: Set[str] = {"static"}
EXCLUDED_RULE_PREFIXES: tuple[str, ...] = ("/static",)
METHODS_TO_SKIP: Set[str] = {"HEAD", "OPTIONS", "TRACE"}
DEFAULT_ARGUMENTS: Dict[str, str] = {
    "token": "sample-token",
    "cep": "01001000",
}


@dataclass(frozen=True)
class RouteCheckFailure:
    rule: str
    endpoint: str
    method: str
    error: str


def _iter_rules(app) -> Iterable:
    for rule in app.url_map.iter_rules():
        if rule.endpoint in EXCLUDED_ENDPOINTS:
            continue
        if any(rule.rule.startswith(prefix) for prefix in EXCLUDED_RULE_PREFIXES):
            continue
        yield rule


def _build_argument_values(rule) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for arg in sorted(rule.arguments):
        if arg in DEFAULT_ARGUMENTS:
            values[arg] = DEFAULT_ARGUMENTS[arg]
            continue
        converter = rule._converters.get(arg)
        converter_name = converter.__class__.__name__ if converter else ""
        if converter_name == "IntegerConverter":
            values[arg] = "1"
        elif converter_name == "UUIDConverter":
            values[arg] = "00000000-0000-0000-0000-000000000000"
        elif converter_name == "PathConverter":
            values[arg] = "sample/path"
        else:
            values[arg] = "sample"
    return values


def test_all_routes_build_urls(app) -> None:
    failures: List[RouteCheckFailure] = []
    with app.test_request_context():
        for rule in _iter_rules(app):
            try:
                url_for(rule.endpoint, **_build_argument_values(rule))
            except Exception as exc:  # pragma: no cover - capture details for assertion
                failures.append(
                    RouteCheckFailure(
                        rule=rule.rule,
                        endpoint=rule.endpoint,
                        method="BUILD",
                        error=str(exc),
                    )
                )
    assert not failures, _format_failures(failures)


def test_static_get_routes_do_not_500(client, app) -> None:
    failures: List[RouteCheckFailure] = []
    for rule in _iter_rules(app):
        if "GET" not in rule.methods:
            continue
        if rule.arguments:
            continue
        if any(method in METHODS_TO_SKIP for method in rule.methods):
            continue

        response = client.get(rule.rule)
        if response.status_code >= 500:
            failures.append(
                RouteCheckFailure(
                    rule=rule.rule,
                    endpoint=rule.endpoint,
                    method="GET",
                    error=f"status={response.status_code}",
                )
            )
    assert not failures, _format_failures(failures)


def _format_failures(failures: List[RouteCheckFailure]) -> str:
    lines = ["Route checks failed:"]
    for failure in failures:
        lines.append(
            f"- {failure.method} {failure.rule} ({failure.endpoint}): {failure.error}"
        )
    return "\n".join(lines)
