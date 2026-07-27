from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_global_toast_formats_object_messages():
    layout = read('templates/layout.html')

    assert 'function formatUserMessage(value' in layout
    assert 'window.formatUserMessage = formatUserMessage' in layout
    assert "const text = formatUserMessage(message" in layout
    assert "textContent = data.message" not in layout


def test_form_feedback_accepts_non_string_messages():
    script = read('static/js/form_feedback.js')

    assert 'function formatMessage(value' in script
    assert "if ('message' in result)" in script
    assert "typeof result.message === 'string'" not in script
