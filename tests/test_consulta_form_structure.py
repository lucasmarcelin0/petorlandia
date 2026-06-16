import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_template(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_clinical_panel_is_not_nested_inside_consulta_form():
    template = read_template("templates/partials/consulta_form.html")

    form_start = template.index('<form id="consulta-form"')
    form_end = template.index("</form>", form_start)
    panel_include = template.index("{% include 'partials/clinical_suggestions_panel.html' %}")

    assert form_end < panel_include


def test_consulta_save_controls_stay_associated_with_form():
    consulta_template = read_template("templates/partials/consulta_form.html")
    panel_template = read_template("templates/partials/clinical_suggestions_panel.html")

    panel_include = consulta_template.index("{% include 'partials/clinical_suggestions_panel.html' %}")
    history_start = consulta_template.index("{% if consulta %}")
    save_section = consulta_template[panel_include:history_start]

    assert re.search(r'<button[^>]+type="submit"[^>]+form="consulta-form"', save_section)
    assert re.search(r'<input[^>]+id="suspeita-clinica"[^>]+form="consulta-form"', consulta_template)
    assert re.search(r'<input[^>]+id="suspeita-clinica"[^>]+form="consulta-form"', panel_template)


def test_clinical_panel_exposes_calculated_plan_controls():
    panel_template = read_template("templates/partials/clinical_suggestions_panel.html")
    prescription_template = read_template("templates/partials/prescricao_form.html")

    assert "data-plan-url" in panel_template
    assert "calcular_plano_sugestao_clinica" in panel_template
    assert "js-load-clinical-plan" in panel_template
    assert "js-apply-plan-medications" in panel_template
    assert "js-apply-plan-medication" in panel_template
    assert "Plano clínico calculado" in panel_template
    assert "Para a receita do tutor" in panel_template
    assert "Medicamentos do protocolo (base técnica)" in panel_template
    assert "item.status === 'ready'" in panel_template
    assert "function displayText" in panel_template
    assert "adicionarPrescricaoCalculadaAoRascunho" in panel_template
    assert "window.adicionarPrescricaoCalculadaAoRascunho" in prescription_template
