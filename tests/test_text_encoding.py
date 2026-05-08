from pathlib import Path
import re


APP_TEXT_ROOTS = [
    "app",
    "blueprints",
    "config",
    "models",
    "providers",
    "repositories",
    "security",
    "services",
    "static",
    "templates",
    "vetsmart_exporter",
]
APP_TEXT_FILES = [
    "admin.py",
    "app.py",
    "app_factory.py",
    "forms.py",
]
TEXT_EXTENSIONS = {".css", ".html", ".js", ".md", ".py", ".txt"}

MOJIBAKE_PATTERN = re.compile(
    r"(?:"
    r"\u00c3[\u0080-\u00bf]|"
    r"\u00c2(?:[\u0080-\u00bf]| )|"
    r"\u00e2[\u0080-\u009f\u20ac\u2020\u2021\u2018-\u2026]|"
    r"\u00f0[\u0080-\u00bf\u0178]|"
    r"\u00ef[\u0080-\u00bf]"
    r")"
)


def _iter_app_text_files():
    root = Path(__file__).resolve().parents[1]
    for relative_file in APP_TEXT_FILES:
        path = root / relative_file
        if path.exists():
            yield path

    for relative_dir in APP_TEXT_ROOTS:
        base = root / relative_dir
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS:
                yield path


def test_application_text_files_do_not_contain_common_mojibake():
    offenders = []
    for path in sorted(set(_iter_app_text_files())):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        match = MOJIBAKE_PATTERN.search(text)
        if match:
            offenders.append(f"{path.relative_to(Path(__file__).resolve().parents[1])}: {match.group(0)!r}")

    assert offenders == []
