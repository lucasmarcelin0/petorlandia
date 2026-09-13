"""Test to prevent silent front-end fetch failures.

Ensures that AJAX calls / fetch responses in templates and static files
provide user feedback upon failure (else clause, error toast, throw, etc.)
rather than dropping failures silently.
"""
import os
import re
import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TEMPLATES_DIR = os.path.join(ROOT_DIR, 'templates')
STATIC_DIR = os.path.join(ROOT_DIR, 'static')
EXCLUDED_SUBDIRS = {'vendor', 'dist', 'lib', 'blender', 'easter_egg'}


def get_front_files():
    files = []
    for base in [TEMPLATES_DIR, STATIC_DIR]:
        for root, dirs, filenames in os.walk(base):
            if any(exc in root for exc in EXCLUDED_SUBDIRS):
                continue
            for f in filenames:
                if f.endswith('.html') or f.endswith('.js'):
                    files.append(os.path.join(root, f))
    return files


def find_silent_ok_checks(content):
    """Find occurrences of `if (<resp>.ok)` where error is not handled."""
    pattern = re.compile(
        r'if\s*\(\s*(?:!\s*)?([a-zA-Z0-9_]+(?:\s*&&\s*[a-zA-Z0-9_]+)?)\.ok\s*\)\s*\{',
        re.MULTILINE
    )
    issues = []
    for m in pattern.finditer(content):
        matched_str = m.group(0)
        if '!' in matched_str:
            continue

        start = m.end() - 1
        brace_count = 0
        end = -1
        for i in range(start, len(content)):
            if content[i] == '{':
                brace_count += 1
            elif content[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break
        if end == -1:
            continue

        block_body = content[start + 1 : end - 1]
        after_block = content[end : end + 300]

        has_else = bool(re.match(r'\s*else\b', after_block))
        has_break = bool(re.search(r'\bbreak\s*;', block_body))
        has_return = bool(re.search(r'\breturn\b', block_body))

        # If the block has an else, or if the block unconditionally returns/breaks,
        # execution continuing past it means the failure case is handled downstream.
        if not has_else and not has_break and not has_return:
            line_no = content[: m.start()].count('\n') + 1
            issues.append((line_no, matched_str.strip()))
    return issues


def test_no_silent_ok_failures_in_critical_templates():
    """Ensure critical templates have no unhandled positive .ok checks."""
    critical_files = [
        os.path.join(TEMPLATES_DIR, 'partials', 'consulta_form.html'),
        os.path.join(TEMPLATES_DIR, 'partials', 'orcamento_form.html'),
        os.path.join(TEMPLATES_DIR, 'partials', 'exames_form.html'),
        os.path.join(TEMPLATES_DIR, 'agendamentos', 'edit_appointment.html'),
    ]
    for path in critical_files:
        assert os.path.exists(path), f"File {path} does not exist"
        with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
            content = fp.read()
        issues = find_silent_ok_checks(content)
        rel_path = os.path.relpath(path, ROOT_DIR).replace('\\', '/')
        assert not issues, f"Found silent .ok checks in {rel_path}: {issues}"


def test_consulta_form_edit_return_has_data_sync_and_csrf():
    """Ensure the return edit form in consulta_form.html uses data-sync pipeline."""
    path = os.path.join(TEMPLATES_DIR, 'partials', 'consulta_form.html')
    with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
        content = fp.read()

    assert 'id="edit-return-form"' in content
    assert 'data-sync' in content
    assert 'action="{{ url_for(\'edit_appointment\'' in content or 'action="{{ url_for("edit_appointment"' in content
    assert 'name="csrf_token"' in content
    assert 'fetch(`/appointments/${formEl.dataset.appointmentId}/edit`' not in content
    assert 'edit-return-form' in content
    assert 'form-sync-success' in content


def test_orcamento_form_has_error_handling():
    """Ensure all 3 budgeting AJAX operations handle failures."""
    path = os.path.join(TEMPLATES_DIR, 'partials', 'orcamento_form.html')
    with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
        content = fp.read()

    assert 'async function criarServico()' in content
    assert 'async function adicionarItemOrcamento()' in content
    assert 'async function removerItemOrcamento(' in content

    issues = find_silent_ok_checks(content)
    assert not issues, f"orcamento_form.html has unhandled .ok checks: {issues}"


def test_global_silent_ok_regression_guard():
    """Global guard ensuring no new unhandled .ok checks exist in templates/static."""
    all_issues = {}
    for path in get_front_files():
        with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
            content = fp.read()
        issues = find_silent_ok_checks(content)
        if issues:
            rel_path = os.path.relpath(path, ROOT_DIR).replace('\\', '/')
            all_issues[rel_path] = issues

    assert not all_issues, f"New silent .ok failures detected in front-end: {all_issues}"
