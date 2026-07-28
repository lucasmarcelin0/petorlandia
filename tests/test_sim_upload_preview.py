import json
import re
from copy import deepcopy
from io import BytesIO
from pathlib import Path

from blueprints.sim import (
    PROCESS_ID,
    SEED_STATE,
    SimProcessState,
    SimSession,
    SimUser,
    build_form_docx,
    now_iso,
)
from extensions import db


def test_uploaded_pdf_can_be_previewed_only_on_same_origin(app):
    token = "sim-preview-test-token"
    legacy_state = deepcopy(SEED_STATE)
    legacy_state["documents"].extend([
        {"id": "mtse", "group": "anexos", "name": "MTSE rascunho"},
        {"id": "planta-fluxo", "group": "anexos", "name": "Croqui de fluxo"},
    ])
    with app.app_context():
        user = SimUser(
            email="preview@example.test",
            name="Estabelecimento de teste",
            role="establishment",
            password_hash="unused",
            created_at=now_iso(),
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(
            SimSession(
                token=token,
                user_id=user.id,
                created_at=now_iso(),
                last_seen_at=now_iso(),
            )
        )
        db.session.add(
            SimProcessState(
                process_id=PROCESS_ID,
                state_json=json.dumps(legacy_state),
                updated_at=now_iso(),
            )
        )
        db.session.commit()

    client = app.test_client()
    authorization = {"Authorization": f"Bearer {token}"}
    state = client.get("/sim/api/state", headers=authorization).get_json()["state"]
    document_ids = {document["id"] for document in state["documents"]}
    assert "mtse" not in document_ids
    assert "planta-fluxo" not in document_ids

    upload = client.post(
        "/sim/api/uploads",
        headers=authorization,
        data={
            "docId": "certidoes-ambientais",
            "file": (BytesIO(b"%PDF-1.4\n%%EOF"), "licenca-ambiental.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200
    upload_id = upload.get_json()["upload"]["id"]

    preview = client.get(
        f"/sim/api/uploads/{upload_id}",
        headers=authorization,
    )

    assert preview.status_code == 200
    assert preview.content_type == "application/pdf"
    assert preview.headers["Content-Disposition"].startswith("inline;")
    assert preview.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert preview.headers["Content-Security-Policy"] == "frame-ancestors 'self'"
    assert preview.headers["Cache-Control"] == "private, no-store"


def test_other_pages_remain_blocked_from_iframes(app):
    response = app.test_client().get("/live")

    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_image_preview_restores_zoom_and_pan_controls():
    project_root = Path(__file__).resolve().parents[1]
    script = (project_root / "static" / "sim_portal" / "app.js").read_text(encoding="utf-8")
    styles = (project_root / "static" / "sim_portal" / "styles.css").read_text(encoding="utf-8")

    assert "function isImageUpload(upload)" in script
    assert 'data-preview-zoom="out"' in script
    assert 'data-preview-zoom="in"' in script
    assert 'data-preview-zoom="actual"' in script
    assert 'data-preview-zoom="fit"' in script
    assert "function bindUploadPreviewControls()" in script
    assert "viewport.scrollLeft" in script
    assert "viewport.scrollTop" in script
    assert ".upload-preview-viewport" in styles
    assert ".preview-zoom-controls" in styles
    assert "cursor: grabbing;" in styles


def test_product_docx_contains_official_anexo_iv_sections():
    state = deepcopy(SEED_STATE)
    product = state["products"][0]
    state["printProductId"] = product["id"]
    product.update({
        "labelTypes": ["Impresso", "Etiqueta"],
        "primaryPackagingTypes": ["Plastico"],
        "dateLotIndication": "Impressao no verso",
        "packageQuantity": "500 g",
        "labelingPresentation": "Rotulo colorido anexado",
        "compositionRows": [{
            "id": "ingredient-test",
            "kind": "Ingrediente",
            "ingredient": "Sal",
            "amount": "0,01 kg",
            "pct": "2%",
        }],
        "storageConditions": "Manter refrigerado",
    })

    document = build_form_docx("produto", state)
    text = "\n".join([
        *(paragraph.text for paragraph in document.paragraphs),
        *(
            cell.text
            for table in document.tables
            for row in table.rows
            for cell in row.cells
        ),
    ])

    for expected in (
        "4. Nome do produto",
        "5. Natureza da solicitacao",
        "6.1 Rotulo",
        "6.2 Embalagem primaria",
        "7. Composicao do produto",
        "8. Informacao nutricional",
        "9. Processo de fabricacao",
        "10. Processo de embalagem",
        "11. Condicoes de armazenamento",
        "12. Medidas de controle de qualidade",
        "13. Transporte e expedicao",
        "Impresso, Etiqueta",
        "Manter refrigerado",
    ):
        assert expected in text

    assert "PREFEITURA MUNICIPAL DE ORLÂNDIA" in text
    assert "1. IDENTIFICAÇÃO DO ESTABELECIMENTO" in text
    assert "5. PROCESSO PRODUTIVO E CONTROLES" in text
    assert document.styles["Normal"].font.size.pt == 12


def test_anexo_i_print_layout_uses_two_isolated_a4_pages():
    project_root = Path(__file__).resolve().parents[1]
    script = (project_root / "static" / "sim_portal" / "app.js").read_text(encoding="utf-8")
    styles = (project_root / "static" / "sim_portal" / "styles.css").read_text(encoding="utf-8")

    assert script.count('<section class="official-page official-anexo-i-page') == 2
    assert "official-field span-" not in script
    assert ".official-span-6 { grid-column: span 6; }" in styles
    assert "@page anexo-i" in styles
    assert "page-break-after: always" in styles
    assert 'data-official-choice-path="application.actType"' in script
    assert "official-fill-input" in script
    assert "lucasferreira@orlandia.sp.gov.br" in script
    assert "(31) 99950-5748" in script
    assert "let persistQueue = Promise.resolve();" in script


def test_annexes_ii_to_vii_use_editable_official_a4_pages():
    project_root = Path(__file__).resolve().parents[1]
    script = (project_root / "static" / "sim_portal" / "app.js").read_text(encoding="utf-8")
    styles = (project_root / "static" / "sim_portal" / "styles.css").read_text(encoding="utf-8")

    expected_pages = {
        "II": 5,
        "III": 2,
        "IV": 3,
        "V": 2,
        "VI": 2,
        "VII": 2,
    }
    for annex, pages in expected_pages.items():
        assert script.count(f'officialDocumentPage("{annex}"') == pages

    assert "function officialTextarea(" in script
    assert 'data-official-array-path="' in script
    assert 'data-path="${path}"' in script
    assert "PREFEITURA MUNICIPAL DE ORL&Acirc;NDIA" in script
    assert "lucasferreira@orlandia.sp.gov.br" in script
    assert "@page official-document" in styles
    assert ".official-document-page + .official-document-page" in styles
    assert ".official-other-option > span" in styles


def test_print_forms_expand_on_screen_and_create_safe_colored_pdf_continuations():
    project_root = Path(__file__).resolve().parents[1]
    script = (project_root / "static" / "sim_portal" / "app.js").read_text(encoding="utf-8")
    styles = (project_root / "static" / "sim_portal" / "styles.css").read_text(encoding="utf-8")

    assert 'data-action="print-digital"' in script
    assert "function autoSizeOfficialTextarea" in script
    assert "function prepareLongFormFields" in script
    assert "official-continuation-page" in script
    assert "O conteúdo integral deste campo segue na página de continuação." in script
    assert "printDocument(\"digital\")" in script
    assert "resize: vertical;" in styles
    assert ".digital-pdf .official-service-masthead" in styles
    assert "body.digital-pdf .official-service-masthead img" in styles
    assert ".official-continuation-text" in styles


def test_printable_forms_use_legible_type_instead_of_shrinking_filled_content():
    project_root = Path(__file__).resolve().parents[1]
    styles = (project_root / "static" / "sim_portal" / "styles.css").read_text(encoding="utf-8")

    assert "font: 500 10pt/1.25 Arial, Helvetica, sans-serif;" in styles
    assert ".official-document-page .official-fill-input" in styles
    assert "font-size: 9.5pt;" in styles
    assert re.search(r"\.official-continuation-text\s*\{[^}]*font-size:\s*10pt;", styles, re.DOTALL)


def test_screen_editing_uses_a_distinct_comfortable_layout_from_printing():
    project_root = Path(__file__).resolve().parents[1]
    styles = (project_root / "static" / "sim_portal" / "styles.css").read_text(encoding="utf-8")

    assert "Tela de preenchimento: conforto visual e hierarquia" in styles
    assert "@media screen" in styles
    assert "min-height: 0;" in styles
    assert "border-radius: 16px;" in styles
    assert "background: linear-gradient(145deg, #ffffff 0%, #f7fbfa 100%);" in styles
    assert "@media print" in styles


def test_official_document_cards_present_a_progressive_three_step_workflow():
    project_root = Path(__file__).resolve().parents[1]
    script = (project_root / "static" / "sim_portal" / "app.js").read_text(encoding="utf-8")
    styles = (project_root / "static" / "sim_portal" / "styles.css").read_text(encoding="utf-8")

    assert 'class="annex-flow" aria-label="Etapas do Anexo ${annex.number}"' in script
    assert script.count('class="annex-flow-step') >= 3
    assert 'class="btn annex-upload-button"' in script
    assert '<details class="annex-details">' in script
    assert "Base legal e orientação de envio" in script
    assert "Histórico de arquivos" in script
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in styles
    assert ".annex-current-file" in styles
    assert ".annex-card-details-grid" in styles


def test_remaining_registry_documents_follow_the_same_visual_workflow():
    project_root = Path(__file__).resolve().parents[1]
    script = (project_root / "static" / "sim_portal" / "app.js").read_text(encoding="utf-8")
    styles = (project_root / "static" / "sim_portal" / "styles.css").read_text(encoding="utf-8")

    assert "function registryDocumentCard" in script
    assert 'class="document-card registry-document' in script
    assert 'class="registry-flow" aria-label="Etapas de ${doc.name}"' in script
    assert "Separe o documento correto" in script
    assert "Orientações e base legal" in script
    assert 'class="span-12 panel registry-documents-panel"' in script
    assert 'class="span-12 panel document-support-panel"' in script
    assert ".document-card.registry-document" in styles
    assert ".registry-flow .annex-flow-step" in styles
    assert ".registry-card-head" in styles
    assert ".document-support-panel" in styles
