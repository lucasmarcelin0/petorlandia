import app  # noqa: F401 - ensure app module is imported so create_app can resolve instance
import pytest

def test_vet_detail_template_a11y_labels():
    with open("templates/veterinarios/vet_detail.html", "r", encoding="utf-8") as f:
        content = f.read()

    assert 'aria-label="Editar horário"' in content
    assert 'aria-label="Excluir horário"' in content
    assert 'i class="fas fa-edit" aria-hidden="true"' in content
    assert 'i class="fas fa-trash" aria-hidden="true"' in content

def test_tutores_adicionados_template_a11y_labels():
    with open("templates/partials/tutores_adicionados.html", "r", encoding="utf-8") as f:
        content = f.read()

    assert 'aria-label="Buscar tutores"' in content
    assert 'i class="fas fa-search" aria-hidden="true"' in content
