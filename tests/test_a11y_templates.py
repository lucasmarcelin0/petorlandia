import app  # noqa: F401 - ensure app module is imported so create_app can resolve instance
import pytest

def test_vet_detail_template_a11y_labels():
    with open("templates/veterinarios/vet_detail.html", "r", encoding="utf-8") as f:
        content = f.read()

    assert 'aria-label="Editar horário"' in content
    assert 'aria-label="Excluir horário"' in content
    assert 'i class="fas fa-edit" aria-hidden="true"' in content
    assert 'i class="fas fa-trash" aria-hidden="true"' in content
    assert 'id="appointmentModalForm"' in content
    assert 'id="appointmentDetailModal"' in content
    assert 'role="dialog"' in content
    assert 'aria-modal="true"' in content
    assert 'aria-labelledby="appointmentModalFormTitle"' in content
    assert 'aria-labelledby="appointmentDetailModalTitle"' in content

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


def test_global_modal_dialog_accessibility_attributes():
    with open("templates/layout.html", "r", encoding="utf-8") as f:
        layout_content = f.read()
    assert 'id="confirmModal"' in layout_content
    assert 'role="dialog"' in layout_content
    assert 'aria-modal="true"' in layout_content
    assert 'aria-labelledby="confirmModalLabel"' in layout_content

    with open("templates/partials/_lead_capture.html", "r", encoding="utf-8") as f:
        lead_content = f.read()
    assert 'id="leadCaptureModal"' in lead_content
    assert 'role="dialog"' in lead_content
    assert 'aria-modal="true"' in lead_content
    assert 'aria-labelledby="leadCaptureTitle"' in lead_content
    assert 'aria-describedby="leadCaptureDescription"' in lead_content

    with open("templates/partials/schedule_modal.html", "r", encoding="utf-8") as f:
        schedule_content = f.read()
    assert 'id="scheduleModal"' in schedule_content
    assert 'role="dialog"' in schedule_content
    assert 'aria-modal="true"' in schedule_content
    assert 'aria-labelledby="scheduleModalTitle"' in schedule_content


def test_appointment_card_template_a11y_icons():
    with open("templates/partials/_appointment_card.html", "r", encoding="utf-8") as f:
        content = f.read()

    assert '<i class="fa-regular fa-clock" aria-hidden="true"></i>' in content
    assert '<i class="fa-solid fa-paw" aria-hidden="true"></i>' in content
    assert '<i class="fa-solid fa-trash" aria-hidden="true"></i>' in content


def test_bulario_search_and_filter_a11y():
    with open("templates/bulario/lista.html", "r", encoding="utf-8") as f:
        content = f.read()

    assert 'aria-label="Buscar medicamento"' in content
    assert 'aria-label="Limpar busca"' in content
    assert 'aria-expanded=' in content
    assert 'aria-controls="drawer-' in content


def test_form_macros_accessibility_attributes():
    with open("templates/components/form_macros.html", "r", encoding="utf-8") as f:
        content = f.read()

    assert '<span class="text-danger" aria-hidden="true">*</span>' in content
    assert "'aria_required': 'true'" in content
    assert "'aria_invalid': 'true'" in content
    assert "field.id ~ '-error'" in content
    assert 'invalid-feedback' in content


def test_listing_panels_btn_group_a11y_labels():
    with open("templates/partials/tutores_adicionados.html", "r", encoding="utf-8") as f:
        tutor_content = f.read()
    assert 'role="group"' in tutor_content
    assert 'aria-label="Filtro de escopo dos tutores"' in tutor_content

    with open("templates/partials/animais_adicionados.html", "r", encoding="utf-8") as f:
        animal_content = f.read()
    assert 'role="group"' in animal_content
    assert 'aria-label="Filtro de escopo dos animais"' in animal_content


def test_home_editor_icon_button_a11y_labels():
    with open("templates/admin/home_editor.html", "r", encoding="utf-8") as f:
        content = f.read()

    assert 'aria-label="{% if flag.enabled %}Ocultar{% else %}Mostrar{% endif %} este botão"' in content
    assert 'aria-label="{% if flag.enabled %}Ocultar{% else %}Mostrar{% endif %} bloco {{ flag.label }}"' in content
    assert 'aria-label="{% if flag_map[\'home_section_pets\'].enabled %}Ocultar{% else %}Mostrar{% endif %} bloco de pets"' in content
    assert 'aria-hidden="true"' in content


def test_copy_buttons_a11y_attributes():
    template_files = [
        ("templates/indicacao.html", 'aria-label="Copiar link de indicação"'),
        ("templates/animais/ficha_animal.html", 'aria-label="Copiar link da carteirinha digital"'),
        ("templates/vacinas_servico/pedido.html", 'aria-label="Copiar link do pedido"'),
        ("templates/admin/parcerias.html", 'aria-label="Copiar link do convite"'),
    ]
    for filepath, expected_label in template_files:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        assert 'aria-live="polite"' in content, f"Missing aria-live='polite' in {filepath}"
        assert expected_label in content, f"Missing expected aria-label in {filepath}"


def test_icon_buttons_a11y_attributes():
    with open("templates/contabilidade/nfse.html", "r", encoding="utf-8") as f:
        nfse_content = f.read()
    assert 'aria-label="Carregar dados do orçamento"' in nfse_content
    assert 'aria-label="Expandir detalhes"' in nfse_content

    with open("templates/partials/consulta_form.html", "r", encoding="utf-8") as f:
        consulta_content = f.read()
    assert 'aria-label="Alternar cronômetro"' in consulta_content


def test_photo_cropper_macro_a11y_attributes():
    with open("templates/components/photo_cropper.html", "r", encoding="utf-8") as f:
        content = f.read()

    assert 'role="group"' in content
    assert 'aria-label="Controles de edição da imagem"' in content
    assert '<i class="fas fa-undo" aria-hidden="true"></i>' in content
    assert '<i class="fas fa-redo" aria-hidden="true"></i>' in content
    assert '<i class="fas fa-search-minus" aria-hidden="true"></i>' in content
    assert '<i class="fas fa-search-plus" aria-hidden="true"></i>' in content
    assert '<i class="fas fa-sync-alt" aria-hidden="true"></i>' in content


def test_management_icon_buttons_a11y_attributes():
    with open("templates/grooming/planos_publicos.html", "r", encoding="utf-8") as f:
        grooming_content = f.read()
    assert 'aria-label="{{ \'Desativar plano \' ~ p.name if p.active else \'Ativar plano \' ~ p.name }}"' in grooming_content

    with open("templates/bulario/form.html", "r", encoding="utf-8") as f:
        bulario_content = f.read()
    assert 'aria-label="Remover apresentação"' in bulario_content

    with open("templates/partials/clinic_info.html", "r", encoding="utf-8") as f:
        clinic_content = f.read()
    assert 'aria-label="Excluir horário de {{ h.dia_semana }}"' in clinic_content

