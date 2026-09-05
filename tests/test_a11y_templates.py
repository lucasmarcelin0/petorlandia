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

def test_contabilidade_dre_and_fluxo_caixa_a11y_labels():
    with open("templates/contabilidade/dre.html", "r", encoding="utf-8") as f:
        dre_content = f.read()
    assert 'aria-label="Filtrar DRE"' in dre_content
    assert 'i class="fas fa-search" aria-hidden="true"' in dre_content

    with open("templates/contabilidade/fluxo_caixa.html", "r", encoding="utf-8") as f:
        fluxo_content = f.read()
    assert 'aria-label="Filtrar fluxo de caixa"' in fluxo_content
    assert 'i class="fas fa-search" aria-hidden="true"' in fluxo_content

def test_sfa_templates_icon_a11y_labels():
    with open("templates/sfa/analise_respostas.html", "r", encoding="utf-8") as f:
        analise_content = f.read()
    assert 'aria-label="Limpar filtros"' in analise_content
    assert 'i class="fas fa-rotate-left" aria-hidden="true"' in analise_content

    with open("templates/sfa/paciente_detail.html", "r", encoding="utf-8") as f:
        detail_content = f.read()
    assert 'aria-label="Atualizar status do WhatsApp"' in detail_content
    assert 'i class="fab fa-whatsapp" aria-hidden="true"' in detail_content

    with open("templates/sfa/dashboard.html", "r", encoding="utf-8") as f:
        dash_content = f.read()
    assert 'aria-label="Abrir conversa no WhatsApp com o paciente"' in dash_content

    with open("templates/sfa/pacientes.html", "r", encoding="utf-8") as f:
        pacientes_content = f.read()
    assert 'aria-label="Ver detalhes do paciente {{ p.id_estudo }}"' in pacientes_content
