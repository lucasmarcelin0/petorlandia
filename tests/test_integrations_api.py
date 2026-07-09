import json
import sys
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from extensions import db
from models import (
    AdminActionNotification,
    Animal,
    AnimalHealthRecord,
    AnimalDocumento,
    Appointment,
    BlocoExames,
    BlocoPrescricao,
    Clinica,
    CarteirinhaImportacao,
    Consulta,
    ExamAppointment,
    ExameImagem,
    ExameSolicitado,
    OAuthAccessToken,
    OAuthClient,
    OAuthRefreshToken,
    Order,
    Prescricao,
    Product,
    ProductVariant,
    User,
    Vacina,
    Veterinario,
    VeterinarianSettings,
)
from time_utils import utcnow


def _create_token(user_id: int, scope: str = "") -> str:
    token_value = f"token-{user_id}-{scope.replace(':', '-') or 'none'}"
    token = OAuthAccessToken(
        client_id="integration-client",
        user_id=user_id,
        access_token=token_value,
        token_type="Bearer",
        scope=scope,
        expires_at=utcnow() + timedelta(minutes=30),
    )
    db.session.add(token)
    db.session.commit()
    return token_value


def _auth_header(token_value: str) -> dict:
    return {"Authorization": f"Bearer {token_value}"}


def test_integrations_endpoint_requires_bearer_token(app, client):
    response = client.get("/api/integrations/pets")

    assert response.status_code == 401
    body = response.get_json()
    assert body["error"]["code"] == "missing_bearer_token"


def test_integrations_endpoint_requires_scope(app, client):
    with app.app_context():
        user = User(name="Tutor", email="tutor-scope@example.com", role="adotante")
        user.set_password("secret123")
        db.session.add(user)
        db.session.commit()
        token_value = _create_token(user.id, scope="profile")

    response = client.get(
        "/api/integrations/pets",
        headers={"Authorization": f"Bearer {token_value}"},
    )

    assert response.status_code == 403
    payload = response.get_json()
    assert payload["error"]["code"] == "insufficient_scope"
    assert "pets:read" in payload["error"]["details"]["missing_scopes"]


def test_chatgpt_oidc_only_access_token_self_heals_for_veterinarian(app, client):
    with app.app_context():
        user = User(name="ChatGPT Vet", email="chatgpt-token@example.com", role="veterinario", worker="veterinario")
        user.set_password("secret123")
        oauth_client = OAuthClient(
            client_id="chatgpt-token-client",
            name="ChatGPT PetOrlandia MCP",
            redirect_uris="https://chatgpt.com/aip/petorlandia/oauth/callback",
            scopes="openid profile email",
        )
        db.session.add_all([user, oauth_client])
        db.session.flush()
        db.session.add(Veterinario(user_id=user.id, crmv="CRMV-TOKEN"))
        refresh = OAuthRefreshToken(
            client_id="chatgpt-token-client",
            user_id=user.id,
            refresh_token="old-chatgpt-refresh-token",
            scope="openid profile email",
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.session.add(refresh)
        db.session.flush()
        access = OAuthAccessToken(
            client_id="chatgpt-token-client",
            user_id=user.id,
            access_token="old-chatgpt-access-token",
            token_type="Bearer",
            scope="openid profile email",
            refresh_token_id=refresh.id,
            expires_at=utcnow() + timedelta(minutes=30),
        )
        db.session.add(access)
        db.session.commit()
        access_id = access.id
        refresh_id = refresh.id

    response = client.get(
        "/api/integrations/pets",
        headers={"Authorization": "Bearer old-chatgpt-access-token"},
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == []
    with app.app_context():
        assert db.session.get(OAuthAccessToken, access_id).revoked_at is None
        assert "pets:read" in db.session.get(OAuthAccessToken, access_id).scope
        assert "exams:write" in db.session.get(OAuthRefreshToken, refresh_id).scope


def test_integrations_me_and_resource_endpoints(app, client):
    with app.app_context():
        tutor = User(name="Tutor Full", email="tutor-full@example.com", role="adotante")
        tutor.set_password("secret123")
        vet_user = User(name="Vet", email="vet-full@example.com", role="veterinario", worker="veterinario")
        vet_user.set_password("secret123")
        db.session.add_all([tutor, vet_user])
        db.session.flush()

        vet = Veterinario(user_id=vet_user.id, crmv="CRMV-123")
        db.session.add(vet)
        db.session.flush()

        pet = Animal(name="Rex", user_id=tutor.id)
        db.session.add(pet)
        db.session.flush()

        appt = Appointment(
            animal_id=pet.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=utcnow() + timedelta(days=1),
            status="scheduled",
            kind="general",
        )
        db.session.add(appt)
        db.session.commit()

        token_value = _create_token(tutor.id, scope="profile pets:read appointments:read")

    me_response = client.get(
        "/api/integrations/me",
        headers={"Authorization": f"Bearer {token_value}"},
    )
    assert me_response.status_code == 200
    assert me_response.get_json()["data"]["sub"]

    pets_response = client.get(
        "/api/integrations/pets",
        headers={"Authorization": f"Bearer {token_value}"},
    )
    assert pets_response.status_code == 200
    pets_payload = pets_response.get_json()["data"]
    assert len(pets_payload) == 1
    assert pets_payload[0]["name"] == "Rex"

    appointments_response = client.get(
        "/api/integrations/appointments",
        headers={"Authorization": f"Bearer {token_value}"},
    )
    assert appointments_response.status_code == 200
    appointments_payload = appointments_response.get_json()["data"]
    assert len(appointments_payload) == 1
    assert appointments_payload[0]["animal_id"] == pets_payload[0]["id"]


def test_image_exam_flow_releases_pdf_to_clinic_and_tutor_only(app, client):
    with app.app_context():
        clinic = Clinica(nome="Angrisano", email="angrisano@example.com")
        other_clinic = Clinica(nome="Outra Clinica")
        tutor = User(name="Rosa", email="rosa-image@example.com", role="adotante")
        tutor.set_password("secret123")
        other_tutor = User(name="Outro Tutor", email="outro-image@example.com", role="adotante")
        other_tutor.set_password("secret123")
        vet_user = User(name="Ultrassonografista", email="ultra-image@example.com", role="veterinario", worker="veterinario")
        vet_user.set_password("secret123")
        clinic_user = User(name="Dono Angrisano", email="dono-angrisano@example.com", role="adotante", worker="colaborador")
        clinic_user.set_password("secret123")
        db.session.add_all([clinic, other_clinic, tutor, other_tutor, vet_user, clinic_user])
        db.session.flush()
        clinic_user.clinica_id = clinic.id
        vet = Veterinario(user_id=vet_user.id, crmv="12345-SP", clinica_id=clinic.id)
        sid = Animal(name="SID", user_id=tutor.id, clinica_id=clinic.id)
        other_pet = Animal(name="NINA", user_id=other_tutor.id, clinica_id=other_clinic.id)
        db.session.add_all([vet, sid, other_pet])
        db.session.commit()

        clinic_id = clinic.id
        tutor_id = tutor.id
        sid_id = sid.id
        other_pet_id = other_pet.id
        vet_token = _create_token(vet_user.id, scope="profile exams:write exams:read clinical_summary:read")
        clinic_token = _create_token(clinic_user.id, scope="profile exams:write exams:read clinical_summary:read")
        tutor_token = _create_token(tutor.id, scope="profile exams:read clinical_summary:read")

    missing_confirmation = client.post(
        "/api/integrations/image-exams",
        headers=_auth_header(vet_token),
        json={
            "animal_id": sid_id,
            "tutor_id": tutor_id,
            "clinica_id": clinic_id,
            "tipo_exame": "Ultrassonografia Abdominal",
            "data_exame": "16/02/2026",
            "profissional_nome": "Ultrassonografista",
            "profissional_crmv": "12345-SP",
        },
    )
    assert missing_confirmation.status_code == 409

    create_response = client.post(
        "/api/integrations/image-exams",
        headers=_auth_header(vet_token),
        json={
            "animal_id": sid_id,
            "tutor_id": tutor_id,
            "clinica_id": clinic_id,
            "tipo_exame": "Ultrassonografia Abdominal",
            "data_exame": "16/02/2026",
            "profissional_nome": "Ultrassonografista",
            "profissional_crmv": "12345-SP",
            "impressao_diagnostica": "Sem alteracoes relevantes.",
            "confirmar_gravacao": "sim",
        },
    )
    assert create_response.status_code == 201
    exame_id = create_response.get_json()["data"]["exame"]["id"]

    with app.app_context():
        exame = db.session.get(ExameImagem, exame_id)
        exame.arquivo_pdf_url = "/static/uploads/laudos_exames/sid.pdf"
        exame.arquivo_pdf_filename = "sid.pdf"
        exame.status = "finalizado"
        db.session.add(exame)
        db.session.commit()

    clinic_before_release = client.get(
        f"/api/integrations/medical-history?animal_id={sid_id}",
        headers=_auth_header(clinic_token),
    )
    assert clinic_before_release.status_code == 200
    assert clinic_before_release.get_json()["data"]["exames"] == []

    release_clinic = client.post(
        "/api/integrations/image-exams/release-clinic",
        headers=_auth_header(vet_token),
        json={"exame_id": exame_id, "clinica_id": clinic_id, "confirmar_gravacao": "sim"},
    )
    assert release_clinic.status_code == 200
    assert release_clinic.get_json()["data"]["exame"]["liberado_para_clinica"] is True

    clinic_history = client.get(
        f"/api/integrations/medical-history?animal_id={sid_id}",
        headers=_auth_header(clinic_token),
    )
    assert clinic_history.status_code == 200
    clinic_payload = clinic_history.get_json()["data"]
    assert clinic_payload["exames"][0]["titulo"] == "Ultrassonografia Abdominal"
    clinic_pdf = clinic_payload["pdfs_disponiveis"][0]
    assert clinic_pdf["filename"] == "sid.pdf"
    assert clinic_pdf["url"].endswith("/static/uploads/laudos_exames/sid.pdf")
    assert "/api/integrations/clinical-document" not in clinic_pdf["url"]
    assert clinic_pdf["api_document_requires_bearer"] is True
    assert "/api/integrations/clinical-document" in clinic_pdf["api_document_url"]
    assert clinic_payload["exames"][0]["pdf_url"] == clinic_pdf["url"]

    mcp_history = client.post(
        "/mcp",
        headers=_auth_header(clinic_token),
        json={
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {"name": "listar_historico_medico_animal", "arguments": {"animal_id": sid_id}},
        },
    )
    assert mcp_history.status_code == 200
    mcp_result = json.loads(mcp_history.get_json()["result"]["content"][0]["text"])
    assert "api_document_url" not in mcp_result["exames"][0]
    assert "api_document_url" not in mcp_result["pdfs_disponiveis"][0]
    assert "/api/integrations/clinical-document" not in mcp_result["pdfs_disponiveis"][0]["url"]

    clinic_invite = client.post(
        "/api/integrations/clinic-first-access-invites",
        headers=_auth_header(vet_token),
        json={"clinica_id": clinic_id, "exame_id": exame_id, "confirmar_gravacao": "sim"},
    )
    assert clinic_invite.status_code == 201
    clinic_history_with_invite = client.get(
        f"/api/integrations/medical-history?animal_id={sid_id}",
        headers=_auth_header(clinic_token),
    )
    clinic_invite_payload = clinic_history_with_invite.get_json()["data"]
    clinic_invite_pdf = clinic_invite_payload["pdfs_disponiveis"][0]
    assert "/primeiro-acesso-clinica/" in clinic_invite_pdf["url"]
    assert "/api/integrations/clinical-document" not in clinic_invite_pdf["url"]
    assert clinic_invite_payload["exames"][0]["portal_url"] == clinic_invite_pdf["url"]
    assert clinic_invite_payload["exames"][0]["shareable_url_type"] == "clinica_portal"

    release_tutor = client.post(
        "/api/integrations/image-exams/release-tutor",
        headers=_auth_header(clinic_token),
        json={"exame_id": exame_id, "tutor_id": tutor_id, "confirmar_gravacao": "sim"},
    )
    assert release_tutor.status_code == 200
    assert release_tutor.get_json()["data"]["exame"]["liberado_para_tutor"] is True

    tutor_history = client.get(
        f"/api/integrations/medical-history?animal_id={sid_id}",
        headers=_auth_header(tutor_token),
    )
    assert tutor_history.status_code == 200
    tutor_payload = tutor_history.get_json()["data"]
    assert len(tutor_payload["exames"]) == 1
    assert tutor_payload["animal"]["name"].lower() == "sid"

    forbidden_other_pet = client.get(
        f"/api/integrations/medical-history?animal_id={other_pet_id}",
        headers=_auth_header(tutor_token),
    )
    assert forbidden_other_pet.status_code == 404


def test_attach_image_exam_pdf_accepts_arquivo_pdf_contract(app, client, monkeypatch):
    app_module = sys.modules[app.import_name]

    class FakeDownloadResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1024 * 1024):
            yield b"%PDF-1.4\nlaudo sid"

    def fake_get(url, timeout=20, stream=True):
        assert url == "https://files.example.test/sid.pdf"
        return FakeDownloadResponse()

    def fake_upload(file_storage, filename, folder="uploads"):
        assert folder == "laudos_exames"
        assert filename.endswith("sid.pdf")
        return "/static/uploads/laudos_exames/sid.pdf"

    monkeypatch.setattr(app_module.requests, "get", fake_get)
    monkeypatch.setattr(app_module, "upload_to_s3", fake_upload)

    with app.app_context():
        clinic = Clinica(nome="Angrisano")
        tutor = User(name="Rosa", email="rosa-attach@example.com", role="adotante")
        tutor.set_password("secret123")
        vet_user = User(name="Ultra Attach", email="ultra-attach@example.com", role="veterinario", worker="veterinario")
        vet_user.set_password("secret123")
        db.session.add_all([clinic, tutor, vet_user])
        db.session.flush()
        db.session.add(Veterinario(user_id=vet_user.id, crmv="12345-SP", clinica_id=clinic.id))
        sid = Animal(name="Sid", user_id=tutor.id, clinica_id=clinic.id)
        db.session.add(sid)
        db.session.flush()
        exame = ExameImagem(
            animal_id=sid.id,
            tutor_id=tutor.id,
            clinica_requisitante_id=clinic.id,
            profissional_id=vet_user.id,
            tipo_exame="Ultrassonografia Abdominal",
            titulo="Ultrassonografia Abdominal",
            status="finalizado",
        )
        db.session.add(exame)
        db.session.commit()
        token_value = _create_token(vet_user.id, scope="profile exams:write exams:read")
        exame_id = exame.id

    response = client.post(
        "/api/integrations/image-exams/pdf",
        headers=_auth_header(token_value),
        json={
            "exame_id": exame_id,
            "arquivo_pdf": {
                "download_url": "https://files.example.test/sid.pdf",
                "file_id": "file_sid_pdf",
                "mime_type": "application/pdf",
                "file_name": "sid.pdf",
            },
            "confirmar_gravacao": "sim",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]["exame"]
    assert payload["documento_id"]
    assert payload["arquivo_pdf_filename"] == "sid.pdf"
    assert payload["pdf_disponivel"] is True


def test_attach_image_exam_pdf_with_attachment_id_string_uses_existing_document(app, client):
    with app.app_context():
        clinic = Clinica(nome="Angrisano")
        tutor = User(name="Rosa", email="rosa-attach-string@example.com", role="adotante")
        tutor.set_password("secret123")
        vet_user = User(name="Ultra Attach String", email="ultra-attach-string@example.com", role="veterinario", worker="veterinario")
        vet_user.set_password("secret123")
        db.session.add_all([clinic, tutor, vet_user])
        db.session.flush()
        db.session.add(Veterinario(user_id=vet_user.id, crmv="12345-SP", clinica_id=clinic.id))
        sid = Animal(name="Sid", user_id=tutor.id, clinica_id=clinic.id)
        db.session.add(sid)
        db.session.flush()
        documento = AnimalDocumento(
            animal_id=sid.id,
            veterinario_id=vet_user.id,
            filename="Ultrassom_SID_Rosa.pdf",
            file_url="/static/uploads/laudos_exames/Ultrassom_SID_Rosa.pdf",
            descricao="Laudo anexado ao exame: Ultrassonografia Abdominal",
        )
        exame = ExameImagem(
            animal_id=sid.id,
            tutor_id=tutor.id,
            clinica_requisitante_id=clinic.id,
            profissional_id=vet_user.id,
            tipo_exame="Ultrassonografia Abdominal",
            titulo="Ultrassonografia Abdominal",
            status="finalizado",
        )
        db.session.add_all([documento, exame])
        db.session.commit()
        token_value = _create_token(vet_user.id, scope="profile exams:write exams:read")
        exame_id = exame.id
        documento_id = documento.id

    response = client.post(
        "/api/integrations/image-exams/pdf",
        headers=_auth_header(token_value),
        json={
            "exame_id": exame_id,
            "attachment_id": "file_00000000000c720e8db5a4fde81bae1a",
            "confirmar_gravacao": "sim",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]["exame"]
    assert payload["documento_id"] == documento_id
    assert payload["arquivo_pdf_filename"] == "Ultrassom_SID_Rosa.pdf"
    assert payload["pdf_disponivel"] is True


def test_medical_history_reconciles_existing_document_with_image_exam(app, client):
    with app.app_context():
        clinic = Clinica(nome="Angrisano")
        tutor = User(name="Rosa", email="rosa-reconcile@example.com", role="adotante")
        tutor.set_password("secret123")
        vet_user = User(name="Ultra Reconcile", email="ultra-reconcile@example.com", role="veterinario", worker="veterinario")
        vet_user.set_password("secret123")
        db.session.add_all([clinic, tutor, vet_user])
        db.session.flush()
        db.session.add(Veterinario(user_id=vet_user.id, crmv="12345-SP", clinica_id=clinic.id))
        sid = Animal(name="Sid", user_id=tutor.id, clinica_id=clinic.id)
        db.session.add(sid)
        db.session.flush()
        documento = AnimalDocumento(
            animal_id=sid.id,
            veterinario_id=vet_user.id,
            filename="Ultrassom_SID_Rosa.pdf",
            file_url="/static/uploads/laudos_exames/Ultrassom_SID_Rosa.pdf",
            descricao="Laudo anexado ao exame: Ultrassonografia Abdominal",
        )
        exame = ExameImagem(
            animal_id=sid.id,
            tutor_id=tutor.id,
            clinica_requisitante_id=clinic.id,
            profissional_id=vet_user.id,
            tipo_exame="Ultrassonografia Abdominal",
            titulo="Ultrassonografia Abdominal",
            status="liberado_para_tutor",
            liberado_para_tutor=True,
        )
        db.session.add_all([documento, exame])
        db.session.commit()
        token_value = _create_token(tutor.id, scope="profile exams:read clinical_summary:read")
        sid_id = sid.id
        documento_id = documento.id
        exame_id = exame.id

    history = client.get(
        f"/api/integrations/medical-history?animal_id={sid_id}",
        headers=_auth_header(token_value),
    )

    assert history.status_code == 200
    payload = history.get_json()["data"]
    serialized_exam = payload["exames"][0]
    assert serialized_exam["id"] == exame_id
    assert serialized_exam["documento_id"] == documento_id
    assert serialized_exam["arquivo_pdf_filename"] == "Ultrassom_SID_Rosa.pdf"
    assert serialized_exam["pdf_disponivel"] is True
    assert serialized_exam["pdf_url"]
    assert serialized_exam["pdf_url"].endswith("/static/uploads/laudos_exames/Ultrassom_SID_Rosa.pdf")
    assert "/api/integrations/clinical-document" not in serialized_exam["pdf_url"]
    assert serialized_exam["download_url"] == serialized_exam["pdf_url"]
    assert serialized_exam["api_document_requires_bearer"] is True
    assert "/api/integrations/clinical-document" in serialized_exam["api_document_url"]
    pdf_summary = payload["pdfs_disponiveis"][0]
    assert pdf_summary["documento_id"] == documento_id
    assert pdf_summary["url"] == serialized_exam["pdf_url"]
    assert "/api/integrations/clinical-document" not in pdf_summary["url"]
    assert "/api/integrations/clinical-document" in pdf_summary["api_document_url"]

    by_document = client.get(
        f"/api/integrations/clinical-document?documento_id={documento_id}",
        headers=_auth_header(token_value),
    )
    assert by_document.status_code == 200
    by_document_payload = by_document.get_json()["data"]
    assert by_document_payload["documento"]["id"] == exame_id
    assert by_document_payload["documento"]["documento_id"] == documento_id
    assert by_document_payload["url_temporaria"] == "/static/uploads/laudos_exames/Ultrassom_SID_Rosa.pdf"
    assert by_document_payload["shareable_url"].endswith("/static/uploads/laudos_exames/Ultrassom_SID_Rosa.pdf")
    assert "/api/integrations/clinical-document" not in by_document_payload["shareable_url"]
    assert by_document_payload["api_document_requires_bearer"] is True
    assert "/api/integrations/clinical-document" in by_document_payload["api_document_url"]

    by_exam = client.get(
        f"/api/integrations/clinical-document?exame_id={exame_id}",
        headers=_auth_header(token_value),
    )
    assert by_exam.status_code == 200
    assert by_exam.get_json()["data"]["url_temporaria"] == "/static/uploads/laudos_exames/Ultrassom_SID_Rosa.pdf"


def test_public_pricing_uses_central_veterinarian_settings(app, client):
    with app.app_context():
        db.session.add(VeterinarianSettings(membership_price="87.50"))
        db.session.commit()

    response = client.get("/api/public/pricing")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["trial_dias_clinica"] == 30
    assert payload["preco_mensal_clinica"] == 87.5
    assert payload["preco_formatado"] == "R$ 87,50"
    assert payload["exibir_preco_no_convite_clinica"] is True
    assert payload["fonte"] == "site_public_pricing"


def test_external_tutor_invite_shows_report_without_price_trial_or_required_signup(app, client):
    with app.app_context():
        clinic = Clinica(nome="Angrisano")
        tutor = User(name="Rosa", email="rosa-invite@example.com", role="adotante")
        tutor.set_password("secret123")
        vet_user = User(name="Ultra", email="ultra-invite@example.com", role="veterinario", worker="veterinario")
        vet_user.set_password("secret123")
        db.session.add_all([clinic, tutor, vet_user])
        db.session.flush()
        vet = Veterinario(user_id=vet_user.id, crmv="12345-SP", clinica_id=clinic.id)
        sid = Animal(name="Sid", user_id=tutor.id, clinica_id=clinic.id)
        db.session.add_all([vet, sid])
        db.session.flush()
        bloco = BlocoExames(animal_id=sid.id)
        db.session.add(bloco)
        db.session.flush()
        solicitado = ExameSolicitado(
            bloco_id=bloco.id,
            nome="Ultrassonografia abdominal",
            status="concluido",
            laudo_url="/static/uploads/laudos_exames/sid.pdf",
        )
        db.session.add(solicitado)
        db.session.flush()
        exame = ExameImagem(
            animal_id=sid.id,
            tutor_id=tutor.id,
            clinica_requisitante_id=clinic.id,
            profissional_id=vet_user.id,
            exame_solicitado_id=solicitado.id,
            tipo_exame="Ultrassonografia abdominal",
            titulo="Ultrassonografia abdominal",
            status="liberado_para_tutor",
            liberado_para_clinica=True,
            liberado_para_tutor=True,
            arquivo_pdf_url="/static/uploads/laudos_exames/sid.pdf",
            arquivo_pdf_filename="sid.pdf",
        )
        db.session.add(exame)
        db.session.commit()
        token_value = _create_token(vet_user.id, scope="profile exams:write")
        tutor_id = tutor.id
        sid_id = sid.id
        exame_id = exame.id

    invite_response = client.post(
        "/api/integrations/tutor-access-invites",
        headers=_auth_header(token_value),
        json={
            "tutor_id": tutor_id,
            "animal_id": sid_id,
            "exame_id": exame_id,
            "confirmar_gravacao": "sim",
        },
    )
    assert invite_response.status_code == 201
    convite = invite_response.get_json()["data"]["convite"]
    assert convite["tipo_convite"] == "acesso_tutor_laudo"
    assert convite["tutor_paga"] is False
    assert convite["permite_visualizar_laudo"] is True
    assert convite["tutor_id"] == tutor_id
    assert convite["animal_id"] == sid_id
    assert convite["exame_id"]
    assert "/acesso-laudo/" in convite["url"]

    response = client.get(f"/acesso-laudo/{convite['token']}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Seu exame foi disponibilizado pela equipe da clinica Angrisano" in html
    assert "Ver laudo agora" in html
    assert "Guardar no meu historico" in html
    assert "/static/uploads/laudos_exames/sid.pdf" in html
    assert "30 dias" not in html
    assert "R$" not in html
    assert "Criar meu acesso gratuito" not in html
    assert "Crie sua conta para acessar o laudo" not in html
    assert "Cadastre-se para liberar o exame" not in html


def test_invites_return_image_exam_id_and_document_when_exam_has_no_requested_exam(app, client):
    with app.app_context():
        clinic = Clinica(nome="Angrisano", email="angrisano-sem-solicitado@example.com")
        tutor = User(name="Rosa", email="rosa-sem-solicitado@example.com", role="adotante")
        tutor.set_password("secret123")
        vet_user = User(name="Ultra Sem Solicitado", email="ultra-sem-solicitado@example.com", role="veterinario", worker="veterinario")
        vet_user.set_password("secret123")
        db.session.add_all([clinic, tutor, vet_user])
        db.session.flush()
        db.session.add(Veterinario(user_id=vet_user.id, crmv="12345-SP", clinica_id=clinic.id))
        sid = Animal(name="Sid", user_id=tutor.id, clinica_id=clinic.id)
        db.session.add(sid)
        db.session.flush()
        documento = AnimalDocumento(
            animal_id=sid.id,
            veterinario_id=vet_user.id,
            filename="Ultrassom_SID_Rosa.pdf",
            file_url="/static/uploads/laudos_exames/Ultrassom_SID_Rosa.pdf",
            descricao="Laudo anexado ao exame: Ultrassonografia Abdominal",
        )
        exame = ExameImagem(
            animal_id=sid.id,
            tutor_id=tutor.id,
            clinica_requisitante_id=clinic.id,
            profissional_id=vet_user.id,
            tipo_exame="Ultrassonografia Abdominal",
            titulo="Ultrassonografia Abdominal",
            status="liberado_para_tutor",
            liberado_para_clinica=True,
            liberado_para_tutor=True,
        )
        db.session.add_all([documento, exame])
        db.session.commit()
        token_value = _create_token(vet_user.id, scope="profile exams:write")
        tutor_id = tutor.id
        sid_id = sid.id
        clinic_id = clinic.id
        exame_id = exame.id
        documento_id = documento.id

    tutor_invite = client.post(
        "/api/integrations/tutor-access-invites",
        headers=_auth_header(token_value),
        json={"tutor_id": tutor_id, "animal_id": sid_id, "exame_id": exame_id, "confirmar_gravacao": "sim"},
    )
    assert tutor_invite.status_code == 201
    tutor_convite = tutor_invite.get_json()["data"]["convite"]
    assert tutor_convite["exame_id"] == exame_id
    assert tutor_convite["documento_id"] == documento_id
    assert tutor_convite["dados_faltantes"] == []

    clinic_invite = client.post(
        "/api/integrations/clinic-first-access-invites",
        headers=_auth_header(token_value),
        json={"clinica_id": clinic_id, "exame_id": exame_id, "confirmar_gravacao": "sim"},
    )
    assert clinic_invite.status_code == 201
    clinic_convite = clinic_invite.get_json()["data"]["convite"]
    assert clinic_convite["exame_id"] == exame_id
    assert clinic_convite["documento_id"] == documento_id
    assert clinic_convite["dados_faltantes"] == []
    assert "/primeiro-acesso-clinica/" in clinic_convite["url"]


def test_external_clinic_invite_shows_trial_and_central_price(app, client):
    with app.app_context():
        db.session.add(VeterinarianSettings(membership_price="91.25"))
        clinic = Clinica(nome="Angrisano", email="angrisano@example.com")
        tutor = User(name="Rosa", email="rosa-clinic-invite@example.com", role="adotante")
        tutor.set_password("secret123")
        vet_user = User(name="Ultra", email="ultra-clinic-invite@example.com", role="veterinario", worker="veterinario")
        vet_user.set_password("secret123")
        db.session.add_all([clinic, tutor, vet_user])
        db.session.flush()
        vet = Veterinario(user_id=vet_user.id, crmv="12345-SP", clinica_id=clinic.id)
        sid = Animal(name="Sid", user_id=tutor.id, clinica_id=clinic.id)
        db.session.add_all([vet, sid])
        db.session.flush()
        bloco = BlocoExames(animal_id=sid.id)
        db.session.add(bloco)
        db.session.flush()
        solicitado = ExameSolicitado(
            bloco_id=bloco.id,
            nome="Ultrassonografia abdominal",
            status="concluido",
            laudo_url="/static/uploads/laudos_exames/sid.pdf",
        )
        db.session.add(solicitado)
        db.session.flush()
        exame = ExameImagem(
            animal_id=sid.id,
            tutor_id=tutor.id,
            clinica_requisitante_id=clinic.id,
            profissional_id=vet_user.id,
            exame_solicitado_id=solicitado.id,
            tipo_exame="Ultrassonografia abdominal",
            titulo="Ultrassonografia abdominal",
            status="liberado_para_clinica",
            liberado_para_clinica=True,
            arquivo_pdf_url="/static/uploads/laudos_exames/sid.pdf",
            arquivo_pdf_filename="sid.pdf",
        )
        db.session.add(exame)
        db.session.commit()
        token_value = _create_token(vet_user.id, scope="profile exams:write")
        clinic_id = clinic.id
        exame_id = exame.id

    invite_response = client.post(
        "/api/integrations/clinic-first-access-invites",
        headers=_auth_header(token_value),
        json={
            "clinica_id": clinic_id,
            "exame_id": exame_id,
            "confirmar_gravacao": "sim",
        },
    )
    assert invite_response.status_code == 201
    convite = invite_response.get_json()["data"]["convite"]
    assert convite["tipo_convite"] == "trial_clinica_exame"
    assert convite["trial_dias"] == 30
    assert convite["pricing_source"] == "site_public_pricing"
    assert convite["preco_formatado"] == "R$ 91,25"
    assert convite["permite_visualizar_exame"] is True
    assert convite["clinica_id"] == clinic_id
    assert convite["exame_id"]
    assert "/primeiro-acesso-clinica/" in convite["url"]
    with app.app_context():
        assert Clinica.query.count() == 1
        linked_clinic = db.session.get(Clinica, clinic_id)
        assert linked_clinic.owner_id is not None
        assert User.query.filter_by(email="angrisano@example.com").count() == 1

    response = client.get(f"/primeiro-acesso-clinica/{convite['token']}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Fornecido com tecnologia PetOrlândia" in html
    assert "Angrisano" in html
    assert "Ver exame recebido" in html
    assert "Gostaria de organizar seus exames e prontuarios da mesma forma?" in html
    assert "Conhecer a solucao" in html
    assert "Ativar painel gratuito por 30 dias" not in html
    assert "R$ 91,25/mês" not in html
    assert "Criar meu acesso gratuito" not in html


def test_integrations_clinical_endpoints_for_veterinarian(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica Clinica")
        db.session.add(clinic)
        db.session.flush()

        vet_user = User(
            name="Dra. Ana",
            email="ana-integrations@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        vet_user.set_password("secret123")
        tutor = User(name="Tutor Resumo", email="tutor-resumo@example.com", role="adotante", clinica_id=clinic.id)
        tutor.set_password("secret123")
        db.session.add_all([vet_user, tutor])
        db.session.flush()

        vet = Veterinario(user_id=vet_user.id, crmv="CRMV-555", clinica_id=clinic.id)
        db.session.add(vet)
        db.session.flush()

        pet = Animal(name="Thor", user_id=tutor.id, clinica_id=clinic.id)
        db.session.add(pet)
        db.session.flush()

        consulta = Consulta(
            animal_id=pet.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            queixa_principal="Vômito e apatia",
            historico_clinico="Sintomas há 2 dias.",
            exame_fisico="Desidratação leve.",
            conduta="Hidratação e dieta leve.",
            exames_solicitados="Hemograma completo",
            status="finalizada",
            finalizada_em=utcnow(),
        )
        db.session.add(consulta)
        db.session.flush()

        agenda_at = (utcnow() + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
        retorno_at = agenda_at + timedelta(hours=2)

        retorno = Appointment(
            animal_id=pet.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=retorno_at,
            status="scheduled",
            kind="retorno",
            consulta_id=consulta.id,
            clinica_id=clinic.id,
        )
        agenda = Appointment(
            animal_id=pet.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=agenda_at,
            status="scheduled",
            kind="consulta",
            clinica_id=clinic.id,
        )
        db.session.add_all([retorno, agenda])

        bloco_prescricao = BlocoPrescricao(
            animal_id=pet.id,
            clinica_id=clinic.id,
            saved_by_id=vet_user.id,
            instrucoes_gerais="Oferecer água em pequenas quantidades e observar vômitos.",
        )
        db.session.add(bloco_prescricao)
        db.session.flush()
        db.session.add(
            Prescricao(
                bloco_id=bloco_prescricao.id,
                animal_id=pet.id,
                medicamento="Omeprazol",
                dosagem="10 mg",
                frequencia="a cada 24h",
                duracao="5 dias",
            )
        )

        bloco_exames = BlocoExames(animal_id=pet.id, observacoes_gerais="Suspeita gastrointestinal")
        db.session.add(bloco_exames)
        db.session.flush()
        db.session.add(
            ExameSolicitado(
                bloco_id=bloco_exames.id,
                nome="Hemograma completo",
                justificativa="Avaliar processo inflamatório",
                status="pendente",
            )
        )

        db.session.add(
            ExamAppointment(
                animal_id=pet.id,
                specialist_id=vet.id,
                requester_id=vet_user.id,
                scheduled_at=utcnow() + timedelta(days=1),
                status="pending",
            )
        )

        db.session.add_all(
            [
                Vacina(
                    animal_id=pet.id,
                    nome="V10",
                    tipo="Reforço",
                    aplicada=False,
                    aplicada_em=date.today() - timedelta(days=7),
                ),
                Vacina(
                    animal_id=pet.id,
                    nome="Antirrábica",
                    tipo="Campanha",
                    aplicada=False,
                    aplicada_em=date.today() + timedelta(days=15),
                ),
            ]
        )
        pet_id = pet.id
        db.session.commit()

        token_value = _create_token(
            vet_user.id,
            scope=(
                "profile pets:read appointments:read clinical_summary:read "
                "consultations:read prescriptions:read exams:read vaccines:read "
                "handoff:read tutor_guidance:generate"
            ),
        )

    headers = {"Authorization": f"Bearer {token_value}"}

    summary_response = client.get(f"/api/integrations/clinical-summary/{pet_id}", headers=headers)
    assert summary_response.status_code == 200
    summary_payload = summary_response.get_json()["data"]
    assert summary_payload["animal"]["nome"] == "Thor"
    assert summary_payload["ultima_consulta"]["queixa_principal"] == "Vômito e apatia"
    assert summary_payload["pendencias"]["vacinas_atrasadas"][0]["nome"] == "V10"

    agenda_response = client.get(
        f"/api/integrations/today-agenda?date={agenda_at.date().isoformat()}",
        headers=headers,
    )
    assert agenda_response.status_code == 200
    agenda_payload = agenda_response.get_json()["data"]
    assert agenda_payload["total_agendamentos"] >= 1
    assert any(item["animal"]["nome"] == "Thor" for item in agenda_payload["agendamentos"])

    pendencias_response = client.get("/api/integrations/clinical-pendencies", headers=headers)
    assert pendencias_response.status_code == 200
    pendencias_payload = pendencias_response.get_json()["data"]
    assert pendencias_payload["resumo"]["vacinas_atrasadas"] == 1
    assert pendencias_payload["resumo"]["retornos_pendentes"] == 1
    assert pendencias_payload["resumo"]["solicitacoes_de_exame_pendentes"] == 1

    guidance_response = client.get(f"/api/integrations/tutor-guidance/{pet_id}", headers=headers)
    assert guidance_response.status_code == 200
    guidance_payload = guidance_response.get_json()["data"]
    assert "Thor" in guidance_payload["rascunho"]
    assert "Omeprazol" in guidance_payload["rascunho"]

    handoff_response = client.get(f"/api/integrations/handoff/{pet_id}", headers=headers)
    assert handoff_response.status_code == 200
    handoff_payload = handoff_response.get_json()["data"]
    assert handoff_payload["animal"]["nome"] == "Thor"
    assert "Handoff clínico" in handoff_payload["handoff_texto"]


def test_integrations_clinical_summary_respects_clinic_scope(app, client):
    with app.app_context():
        clinic_a = Clinica(nome="Clinica A")
        clinic_b = Clinica(nome="Clinica B")
        db.session.add_all([clinic_a, clinic_b])
        db.session.flush()

        tutor = User(name="Tutor Escopo", email="tutor-escopo@example.com", role="adotante", clinica_id=clinic_a.id)
        tutor.set_password("secret123")
        vet_user = User(
            name="Dra. Escopo",
            email="vet-escopo@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic_b.id,
        )
        vet_user.set_password("secret123")
        db.session.add_all([tutor, vet_user])
        db.session.flush()

        db.session.add(Veterinario(user_id=vet_user.id, crmv="CRMV-777", clinica_id=clinic_b.id))
        db.session.flush()

        pet = Animal(name="Bolt", user_id=tutor.id, clinica_id=clinic_a.id)
        db.session.add(pet)
        db.session.flush()
        pet_id = pet.id
        db.session.commit()

        token_value = _create_token(vet_user.id, scope="profile clinical_summary:read")

    response = client.get(
        f"/api/integrations/clinical-summary/{pet_id}",
        headers={"Authorization": f"Bearer {token_value}"},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "animal_not_found"


def test_integrations_openapi_contract_exposes_chatgpt_actions(app, client):
    response = client.get("/api/integrations/openapi.json")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["openapi"] == "3.1.0"
    assert isinstance(payload["components"]["schemas"], dict)
    assert "PetOrlandiaOAuth" in payload["components"]["securitySchemes"]
    scopes = payload["components"]["securitySchemes"]["PetOrlandiaOAuth"]["flows"]["authorizationCode"]["scopes"]
    assert isinstance(scopes["profile"], str)
    assert "/api/integrations/tutors-with-pets" in payload["paths"]
    create_registration = payload["paths"]["/api/integrations/tutors-with-pets"]["post"]
    assert create_registration["x-openai-isConsequential"] is True
    assert create_registration["operationId"] == "cadastrarTutorEPetsPetOrlandia"
    operation_ids = {
        spec["post"]["operationId"]
        for spec in payload["paths"].values()
        if isinstance(spec, dict) and "post" in spec and "operationId" in spec["post"]
    }
    operation_ids.update(
        spec["get"]["operationId"]
        for spec in payload["paths"].values()
        if isinstance(spec, dict) and "get" in spec and "operationId" in spec["get"]
    )
    assert {
        "criarExameImagemPetOrlandia",
        "anexarPdfExameImagemPetOrlandia",
        "liberarExameParaClinicaPetOrlandia",
        "liberarExameParaTutorPetOrlandia",
        "gerarConvitePrimeiroAcessoClinicaPetOrlandia",
        "gerarConviteAcessoTutorPetOrlandia",
        "listarHistoricoMedicoAnimalPetOrlandia",
        "obterDocumentoClinicoPetOrlandia",
        "buscarOuCriarClinicaRequisitantePetOrlandia",
        "buscarOuCriarTutorAnimalPetOrlandia",
    }.issubset(operation_ids)


def test_integrations_rest_write_requires_explicit_confirmation(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica REST Confirmacao")
        db.session.add(clinic)
        db.session.flush()
        vet_user = User(
            name="Dra. REST",
            email="rest-confirmacao@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        vet_user.set_password("secret123")
        db.session.add(vet_user)
        db.session.flush()
        db.session.add(Veterinario(user_id=vet_user.id, crmv="CRMV-REST", clinica_id=clinic.id))
        db.session.commit()
        token_value = _create_token(vet_user.id, scope="tutors:write pets:write")

    response = client.post(
        "/api/integrations/tutors-with-pets",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "tutor": {"nome": "Tutor Sem Confirmacao"},
            "pets": [{"nome": "Nina"}],
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload["error"]["code"] == "confirmation_required"


def test_integrations_rest_write_routes_create_records(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica REST Actions")
        db.session.add(clinic)
        db.session.flush()

        vet_user = User(
            name="Dra. Actions",
            email="actions-rest@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        vet_user.set_password("secret123")
        db.session.add(vet_user)
        db.session.flush()
        db.session.add(Veterinario(user_id=vet_user.id, crmv="CRMV-ACTIONS", clinica_id=clinic.id))
        db.session.commit()

        token_value = _create_token(
            vet_user.id,
            scope="profile tutors:write pets:write consultations:write exams:write appointments:write pets:read",
        )

    headers = {"Authorization": f"Bearer {token_value}"}
    registration = client.post(
        "/api/integrations/tutors-with-pets",
        headers=headers,
        json={
            "confirmar_gravacao": "sim",
            "tutor": {"nome": "Marcia Cliente", "telefone": "16999990000"},
            "pets": [{"nome": "Lili", "especie": "gato"}],
            "observacao_clinica": "Apetite reduzido.",
        },
    )

    assert registration.status_code == 201
    animal_id = registration.get_json()["data"]["pets"][0]["id"]

    consultation = client.post(
        "/api/integrations/consultations",
        headers=headers,
        json={
            "confirmar_gravacao": "sim",
            "animal_id": animal_id,
            "queixa_principal": "Apatia",
            "diagnostico": "Suspeita gastrointestinal",
            "conduta": "Observacao e dieta leve",
            "finalizar": True,
        },
    )
    assert consultation.status_code == 201
    consulta_id = consultation.get_json()["data"]["consulta_id"]

    exam_block = client.post(
        "/api/integrations/exam-blocks",
        headers=headers,
        json={
            "confirmar_gravacao": "sim",
            "animal_id": animal_id,
            "exames": [{"nome": "Hemograma", "status": "pendente"}],
        },
    )
    assert exam_block.status_code == 201
    assert exam_block.get_json()["data"]["total_exames"] == 1

    appointment = client.post(
        "/api/integrations/appointments",
        headers=headers,
        json={
            "confirmar_gravacao": "sim",
            "animal_id": animal_id,
            "data": (utcnow() + timedelta(days=2)).date().isoformat(),
            "hora": "09:30",
            "tipo": "consulta",
            "motivo": "Reavaliacao",
        },
    )
    assert appointment.status_code == 201

    return_appointment = client.post(
        "/api/integrations/returns",
        headers=headers,
        json={
            "confirmar_gravacao": "sim",
            "consulta_id": consulta_id,
            "data": (utcnow() + timedelta(days=7)).date().isoformat(),
            "hora": "10:00",
            "motivo": "Retorno clinico",
        },
    )
    assert return_appointment.status_code == 201

    with app.app_context():
        tutor = User.query.filter_by(name="Marcia Cliente").one()
        pet = Animal.query.filter_by(id=animal_id).one()
        assert pet.user_id == tutor.id
        assert Consulta.query.filter_by(id=consulta_id, animal_id=animal_id).one().status == "finalizada"
        assert ExameSolicitado.query.count() == 1
        assert Appointment.query.filter_by(animal_id=animal_id).count() >= 2


def test_mcp_clinical_tools_return_structured_payload(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica MCP Operacional")
        db.session.add(clinic)
        db.session.flush()

        vet_user = User(
            name="Dra. Julia",
            email="julia-mcp@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        vet_user.set_password("secret123")
        tutor = User(name="Tutor MCP", email="tutor-mcp@example.com", role="adotante", clinica_id=clinic.id)
        tutor.set_password("secret123")
        db.session.add_all([vet_user, tutor])
        db.session.flush()

        vet = Veterinario(user_id=vet_user.id, crmv="CRMV-888", clinica_id=clinic.id)
        db.session.add(vet)
        db.session.flush()

        pet = Animal(name="Luna", user_id=tutor.id, clinica_id=clinic.id)
        db.session.add(pet)
        db.session.flush()

        consulta = Consulta(
            animal_id=pet.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            queixa_principal="Coceira intensa",
            conduta="Banho terapêutico e retorno",
            status="finalizada",
            finalizada_em=utcnow(),
        )
        db.session.add(consulta)
        db.session.flush()

        db.session.add(
            Appointment(
                animal_id=pet.id,
                tutor_id=tutor.id,
                veterinario_id=vet.id,
                scheduled_at=utcnow() + timedelta(hours=4),
                status="scheduled",
                kind="retorno",
                consulta_id=consulta.id,
                clinica_id=clinic.id,
            )
        )
        pet_id = pet.id
        db.session.commit()

        token_value = _create_token(
            vet_user.id,
            scope="profile appointments:read clinical_summary:read handoff:read tutor_guidance:generate exams:read vaccines:read",
        )

    summary_response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {"name": "obter_resumo_clinico_animal", "arguments": {"animal_id": pet_id}},
        },
    )
    assert summary_response.status_code == 200
    summary_payload = summary_response.get_json()
    summary_result = json.loads(summary_payload["result"]["content"][0]["text"])
    assert summary_result["animal"]["nome"] == "Luna"

    guidance_response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {"name": "gerar_orientacao_tutor", "arguments": {"animal_id": pet_id}},
        },
    )
    assert guidance_response.status_code == 200
    guidance_payload = guidance_response.get_json()
    guidance_result = json.loads(guidance_payload["result"]["content"][0]["text"])
    assert "Luna" in guidance_result["rascunho"]


def test_mcp_freeform_intake_tool_interprets_fragmented_messages(app, client):
    with app.app_context():
        user = User(name="Dra. Intake", email="intake@example.com", role="veterinario", worker="veterinario")
        user.set_password("secret123")
        db.session.add(user)
        db.session.flush()
        db.session.add(Veterinario(user_id=user.id, crmv="CRMV-3030"))
        db.session.commit()

        token_value = _create_token(user.id, scope="profile")

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 23,
            "method": "tools/call",
            "params": {
                "name": "interpretar_mensagem_livre_atendimento",
                "arguments": {
                    "texto": (
                        "[08:21, 16/04/2026] Lucas Marcelino: https://maps.app.goo.gl/nFF8JyXoX74zhyR6A\n"
                        "[23:25, 16/04/2026] Lucas Marcelino: Ligia\n"
                        "[23:40, 16/04/2026] Lucas Marcelino: "
                    )
                },
            },
        },
    )

    assert response.status_code == 200
    payload = json.loads(response.get_json()["result"]["content"][0]["text"])
    assert payload["acao_sugerida"] == "cadastrar_tutor_e_pets"
    assert payload["rascunho_operacional"]["tutor"]["nome"] == "Ligia"
    assert payload["rascunho_operacional"]["tutor"]["endereco_referencia"]
    assert "nome_do_pet" in payload["campos_a_confirmar"]
    assert payload["mensagens_processadas"] == 3


def test_mcp_operational_assistant_executes_registration_from_natural_text(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica Assistente Cadastro")
        db.session.add(clinic)
        db.session.flush()

        user = User(
            name="Dra. Assistente",
            email="assistente-cadastro@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        user.set_password("secret123")
        db.session.add(user)
        db.session.flush()
        db.session.add(Veterinario(user_id=user.id, crmv="CRMV-4040", clinica_id=clinic.id))
        db.session.commit()

        token_value = _create_token(user.id, scope="profile tutors:write pets:write")

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 24,
            "method": "tools/call",
            "params": {
                "name": "assistente_operacional_veterinario",
                "arguments": {
                    "texto": (
                        "Cadastrar tutor Ligia. Telefone: 16999990000. "
                        "Endereço: Rua das Flores, 10. Pet: Mel. Espécie: cão. "
                        "Observação clínica: tosse leve."
                    ),
                    "confirmar_gravacao": "sim",
                },
            },
        },
    )

    assert response.status_code == 200
    payload = json.loads(response.get_json()["result"]["content"][0]["text"])
    assert payload["executado"] is True
    assert payload["acao_sugerida"] == "cadastrar_tutor_e_pets"
    assert payload["resultado_execucao"]["acao_executada"] == "cadastrar_tutor_e_pets"

    with app.app_context():
        tutor = User.query.filter_by(name="Ligia").one()
        pet = Animal.query.filter_by(name="Mel", user_id=tutor.id).one()
        assert tutor.phone == "16999990000"
        assert pet.species and pet.species.name == "Cachorro"


def test_mcp_operational_assistant_executes_scheduling_from_natural_text(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica Assistente Agenda")
        db.session.add(clinic)
        db.session.flush()

        tutor = User(name="Tutor Agenda", email="tutor-agenda@example.com", role="adotante", clinica_id=clinic.id)
        tutor.set_password("secret123")
        user = User(
            name="Dra. Agenda",
            email="assistente-agenda@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        user.set_password("secret123")
        db.session.add_all([tutor, user])
        db.session.flush()

        vet = Veterinario(user_id=user.id, crmv="CRMV-5050", clinica_id=clinic.id)
        db.session.add(vet)
        db.session.flush()

        pet = Animal(name="Rex", user_id=tutor.id, clinica_id=clinic.id)
        db.session.add(pet)
        db.session.commit()

        target_date = (utcnow() + timedelta(days=2)).date().isoformat()
        token_value = _create_token(user.id, scope="profile appointments:write")

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 25,
            "method": "tools/call",
            "params": {
                "name": "assistente_operacional_veterinario",
                "arguments": {
                    "texto": (
                        f"Agendar consulta para pet Rex em {target_date} às 09:30. "
                        "Motivo: retorno respiratório."
                    ),
                    "confirmar_gravacao": "sim",
                },
            },
        },
    )

    assert response.status_code == 200
    payload = json.loads(response.get_json()["result"]["content"][0]["text"])
    assert payload["executado"] is True
    assert payload["acao_sugerida"] == "agendar_consulta"
    assert payload["resultado_execucao"]["resultado"]["tipo"] == "retorno"


def test_mcp_write_tools_create_records(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica Writes")
        db.session.add(clinic)
        db.session.flush()

        vet_user = User(
            name="Dra. Helena",
            email="helena-writes@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        vet_user.set_password("secret123")
        db.session.add(vet_user)
        db.session.flush()

        vet = Veterinario(user_id=vet_user.id, crmv="CRMV-9090", clinica_id=clinic.id)
        db.session.add(vet)
        db.session.commit()

        token_value = _create_token(
            vet_user.id,
            scope=(
                "profile tutors:write pets:write appointments:write consultations:write "
                "exams:write pets:read appointments:read"
            ),
        )

    headers = {"Authorization": f"Bearer {token_value}"}

    register_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {
                "name": "cadastrar_tutor_e_pets",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "tutor": {
                        "nome": "Carlos Tutor",
                        "telefone": "16999990000",
                        "endereco": "Rua A, 10",
                    },
                    "pets": [
                        {
                            "nome": "Meg",
                            "especie": "cao",
                            "idade": "3 anos",
                            "sexo": "Fêmea",
                        }
                    ],
                    "observacao_clinica": "Paciente com tosse recorrente.",
                    "disponibilidade": "Preferência por manhã.",
                },
            },
        },
    )
    assert register_response.status_code == 200
    register_result = json.loads(register_response.get_json()["result"]["content"][0]["text"])
    animal_id = register_result["pets"][0]["id"]

    consulta_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 32,
            "method": "tools/call",
            "params": {
                "name": "registrar_consulta_clinica",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "animal_id": animal_id,
                    "queixa_principal": "Tosse há uma semana",
                    "historico_clinico": "Sem febre, apetite preservado.",
                    "exame_fisico": "Ausculta com ruído leve.",
                    "diagnostico": "Suspeita de traqueobronquite",
                    "conduta": "Nebulização e monitoramento",
                    "exames_solicitados": "Radiografia torácica",
                    "finalizar": True,
                },
            },
        },
    )
    assert consulta_response.status_code == 200
    consulta_result = json.loads(consulta_response.get_json()["result"]["content"][0]["text"])
    consulta_id = consulta_result["consulta_id"]
    assert consulta_result["status"] == "finalizada"

    exames_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 33,
            "method": "tools/call",
            "params": {
                "name": "registrar_bloco_exames",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "animal_id": animal_id,
                    "observacoes_gerais": "Investigar padrão respiratório.",
                    "exames": [
                        {
                            "nome": "Radiografia torácica",
                            "justificativa": "Avaliar padrão pulmonar",
                            "status": "pendente",
                        }
                    ],
                },
            },
        },
    )
    assert exames_response.status_code == 200
    exames_result = json.loads(exames_response.get_json()["result"]["content"][0]["text"])
    assert exames_result["total_exames"] == 1

    agendamento_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 34,
            "method": "tools/call",
            "params": {
                "name": "agendar_consulta",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "animal_id": animal_id,
                    "data": (utcnow() + timedelta(days=2)).date().isoformat(),
                    "hora": "09:30",
                    "tipo": "consulta",
                    "motivo": "Retorno respiratório",
                },
            },
        },
    )
    assert agendamento_response.status_code == 200
    agendamento_result = json.loads(agendamento_response.get_json()["result"]["content"][0]["text"])
    assert agendamento_result["tipo"] == "consulta"

    retorno_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 35,
            "method": "tools/call",
            "params": {
                "name": "agendar_retorno",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "consulta_id": consulta_id,
                    "data": (utcnow() + timedelta(days=7)).date().isoformat(),
                    "hora": "10:00",
                    "motivo": "Reavaliar evolução clínica",
                },
            },
        },
    )
    assert retorno_response.status_code == 200
    retorno_result = json.loads(retorno_response.get_json()["result"]["content"][0]["text"])
    assert retorno_result["success"] is True

    with app.app_context():
        tutor = User.query.filter_by(name="Carlos Tutor").one()
        pet = Animal.query.filter_by(id=animal_id).one()
        assert tutor.email.endswith("@cadastro.petorlandia.local")
        assert pet.user_id == tutor.id
        consulta = db.session.get(Consulta, consulta_id)
        assert "Diagnóstico" in (consulta.conduta or "")
        assert ExameSolicitado.query.count() == 1
        assert Appointment.query.filter_by(animal_id=animal_id).count() >= 2


def test_mcp_registration_tool_requires_write_scopes(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica MCP")
        db.session.add(clinic)
        db.session.flush()

        professional = User(
            name="Colaborador",
            email="colaborador-mcp@example.com",
            role="adotante",
            worker="colaborador",
            clinica_id=clinic.id,
        )
        professional.set_password("secret123")
        db.session.add(professional)
        db.session.commit()

        token_value = _create_token(professional.id, scope="profile pets:read")

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "cadastrar_tutor_e_pets",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "tutor": {"nome": "Nelson Benedito"},
                    "pets": [{"nome": "Marron"}],
                },
            },
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["error"]["code"] == -32003
    assert "tutors:write" in payload["error"]["data"]["missing_scopes"]
    assert "pets:write" in payload["error"]["data"]["missing_scopes"]


def test_mcp_registration_tool_requires_veterinarian_profile(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica Restrita")
        db.session.add(clinic)
        db.session.flush()

        user = User(
            name="Atendente",
            email="atendente-restrito@example.com",
            role="adotante",
            worker="colaborador",
            clinica_id=clinic.id,
        )
        user.set_password("secret123")
        db.session.add(user)
        db.session.commit()

        token_value = _create_token(
            user.id,
            scope="profile tutors:write pets:write pets:read appointments:read",
        )

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "cadastrar_tutor_e_pets",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "tutor": {"nome": "Nelson Benedito"},
                    "pets": [{"nome": "Marron"}],
                },
            },
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["error"]["code"] == -32003
    assert "veterinarian accounts" in payload["error"]["message"]


def test_mcp_importar_laudo_volante_creates_clinic_patient_and_exam(app, client):
    with app.app_context():
        professional = User(
            name="Dr. Ultra",
            email="ultra-volante@example.com",
            role="veterinario",
            worker="veterinario",
        )
        professional.set_password("secret123")
        db.session.add(professional)
        db.session.flush()
        db.session.add(Veterinario(user_id=professional.id, crmv="CRMV-US-1"))
        db.session.commit()

        token_value = _create_token(
            professional.id,
            scope="profile tutors:write pets:write exams:write exams:read clinical_summary:read",
        )

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 41,
            "method": "tools/call",
            "params": {
                "name": "importar_laudo_volante",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "clinica": {
                        "nome": "Clinica Parceira do Laudo",
                        "email": "contato@parceira.example",
                    },
                    "tutor": {
                        "nome": "Marina Tutora",
                        "telefone": "16999990000",
                    },
                    "animal": {
                        "nome": "Luna",
                        "especie": "canina",
                        "sexo": "Femea",
                    },
                    "exame": {
                        "nome": "Ultrassonografia abdominal",
                        "data": "2026-06-07",
                        "conclusao": "Sem alteracoes relevantes.",
                    },
                    "laudo_texto": "Laudo completo: estruturas abdominais preservadas.",
                    "mensagem_clinica": "Laudo finalizado e disponivel no PetOrlandia.",
                },
            },
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["clinica"]["criada_agora"] is True
    assert result["clinica"]["nome"] == "Clinica Parceira do Laudo"
    assert result["animal"]["nome"] == "Luna"
    assert result["exame"]["status"] == "concluido"
    assert result["exame"]["data_realizacao"] == "2026-06-07"
    assert result["exame"]["arquivo_status"] == "sem_arquivo"
    assert "Laudo finalizado" in result["mensagem_sugerida_para_clinica"]
    assert result["links"]["clinica"] == result["links_primeiro_acesso"]["clinica"]
    assert result["links"]["tutor"] == result["links_primeiro_acesso"]["tutor"]
    assert result["comunicacao"]["clinica"]["url"] == result["links_primeiro_acesso"]["clinica"]
    assert result["comunicacao"]["tutor"]["url"] == result["links_primeiro_acesso"]["tutor"]
    assert result["comunicacao"]["tutor"]["whatsapp_url"].startswith("https://wa.me/55")
    assert "mensagem_sugerida_para_tutor" in result
    assert payload["result"]["structuredContent"]["animal"]["nome"] == "Luna"


def test_mcp_importar_laudo_volante_accepts_chatgpt_file_reference(app, client, monkeypatch):
    app_module = sys.modules[app.import_name]

    class FakeDownloadResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1024 * 1024):
            yield b"%PDF-1.4\nlaudo de teste"

    def fake_get(url, timeout=20, stream=True):
        assert url == "https://files.example.test/laudo.pdf"
        assert timeout == 20
        assert stream is True
        return FakeDownloadResponse()

    def fake_upload(file_storage, filename, folder="uploads"):
        assert folder == "laudos_exames"
        assert filename.endswith("laudo.pdf")
        assert file_storage.content_type == "application/pdf"
        return "/static/uploads/laudos_exames/salvo-laudo.pdf"

    monkeypatch.setattr(app_module.requests, "get", fake_get)
    monkeypatch.setattr(app_module, "upload_to_s3", fake_upload)

    with app.app_context():
        professional = User(
            name="Dra. Arquivo",
            email="arquivo-laudo@example.com",
            role="veterinario",
            worker="veterinario",
        )
        professional.set_password("secret123")
        db.session.add(professional)
        db.session.flush()
        db.session.add(Veterinario(user_id=professional.id, crmv="CRMV-FILE"))
        db.session.commit()

        token_value = _create_token(
            professional.id,
            scope="profile tutors:write pets:write exams:write exams:read clinical_summary:read",
        )

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {
                "name": "importar_laudo_volante",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "clinica": {"nome": "Clinica File Ref"},
                    "tutor": {"nome": "Tutor File Ref", "telefone": "16999991111"},
                    "animal": {"nome": "Rosa", "especie": "felina"},
                    "exame": {"nome": "Ultrassom", "conclusao": "Sem alteracoes."},
                    "laudo_arquivo": {
                        "download_url": "https://files.example.test/laudo.pdf",
                        "file_id": "file_laudo_123",
                        "mime_type": "application/pdf",
                        "file_name": "laudo.pdf",
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    result = json.loads(response.get_json()["result"]["content"][0]["text"])
    assert result["animal"]["nome"] == "Rosa"
    assert result["exame"]["laudo_url"] == "/static/uploads/laudos_exames/salvo-laudo.pdf"
    assert result["exame"]["laudo_filename"] == "laudo.pdf"
    assert result["exame"]["arquivo_status"] == "arquivo_salvo"


def test_mcp_importar_laudo_volante_attaches_file_without_rewriting_existing_exam(app, client, monkeypatch):
    app_module = sys.modules[app.import_name]

    class FakeDownloadResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1024 * 1024):
            yield b"%PDF-1.4\nlaudo atualizado"

    monkeypatch.setattr(app_module.requests, "get", lambda *args, **kwargs: FakeDownloadResponse())
    monkeypatch.setattr(
        app_module,
        "upload_to_s3",
        lambda file_storage, filename, folder="uploads": "/static/uploads/laudos_exames/anexo.pdf",
    )

    with app.app_context():
        professional = User(name="Dr. Robson", email="robson-modelo@example.com", role="veterinario", worker="veterinario")
        professional.set_password("secret123")
        clinic = Clinica(nome="Angrisano")
        tutor = User(name="Rosa", email="rosa-anexo@example.com")
        tutor.set_password("secret123")
        animal = Animal(name="Sid", owner=tutor, clinica=clinic)
        db.session.add_all([professional, clinic, tutor, animal])
        db.session.flush()
        db.session.add(Veterinario(user_id=professional.id, crmv="CRMV-ROBSON"))
        bloco = BlocoExames(animal=animal, observacoes_gerais="Pedido original")
        exam = ExameSolicitado(
            bloco=bloco,
            nome="Ultrassonografia abdominal",
            status="concluido",
            resultado="Resultado original que nao deve ser alterado.",
            performed_at=datetime(2026, 2, 16),
        )
        db.session.add_all([bloco, exam])
        db.session.commit()
        exam_id = exam.id
        token_value = _create_token(professional.id, scope="profile tutors:write pets:write exams:write")

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 43,
            "method": "tools/call",
            "params": {
                "name": "importar_laudo_volante",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "exame_id": exam_id,
                    "clinica": {"nome": "Angrisano"},
                    "tutor": {"nome": "Rosa"},
                    "animal": {"nome": "Sid", "especie": "canina"},
                    "exame": {"nome": "Ultrassonografia abdominal", "conclusao": "Texto novo que nao deve substituir."},
                    "laudo_arquivo": {
                        "download_url": "https://files.example.test/anexo.pdf",
                        "file_id": "file_anexo_123",
                        "mime_type": "application/pdf",
                        "file_name": "Ultrassom SID,Rosa.pdf",
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    result = json.loads(response.get_json()["result"]["content"][0]["text"])
    assert result["exame"]["modo_importacao"] == "anexo_em_exame_existente"
    assert result["exame"]["exame_id"] == exam_id
    assert result["exame"]["laudo_url"] == "/static/uploads/laudos_exames/anexo.pdf"
    assert result["exame"]["laudo_filename"] == "Ultrassom_SIDRosa.pdf"
    assert result["links_primeiro_acesso"]["clinica"]
    assert result["links_primeiro_acesso"]["tutor"]
    invite_path = urlparse(result["links_primeiro_acesso"]["clinica"]).path
    invite_response = client.get(invite_path)
    assert invite_response.status_code == 200
    invite_html = invite_response.get_data(as_text=True)
    assert "Fornecido com tecnologia PetOrlândia" in invite_html
    assert "Angrisano" in invite_html
    assert "Gostaria de organizar seus exames e prontuarios da mesma forma?" in invite_html
    with app.app_context():
        db.session.remove()
        saved = db.session.get(ExameSolicitado, exam_id)
        assert saved.resultado == "Resultado original que nao deve ser alterado."


def test_mcp_importar_laudo_volante_ignores_unreachable_chatgpt_local_path(app, client):
    with app.app_context():
        professional = User(
            name="Dra. Caminho Local",
            email="local-path-laudo@example.com",
            role="veterinario",
            worker="veterinario",
        )
        professional.set_password("secret123")
        db.session.add(professional)
        db.session.flush()
        db.session.add(Veterinario(user_id=professional.id, crmv="CRMV-LOCAL"))
        db.session.commit()

        token_value = _create_token(
            professional.id,
            scope="profile tutors:write pets:write exams:write",
        )

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 43,
            "method": "tools/call",
            "params": {
                "name": "importar_laudo_volante",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "clinica": {"nome": "Clinica Local Path"},
                    "tutor": {"nome": "Tutor Local", "telefone": "16999992222"},
                    "animal": {"nome": "SID", "especie": "canina"},
                    "exame": {"nome": "Ultrassom", "conclusao": "Laudo estruturado importado."},
                    "laudo_url": "/mnt/data/Ultrassom SID,Rosa.pdf",
                    "laudo_filename": "Ultrassom SID,Rosa.pdf",
                },
            },
        },
    )

    assert response.status_code == 200
    result = json.loads(response.get_json()["result"]["content"][0]["text"])
    assert result["exame"]["laudo_url"] is None
    assert result["exame"]["laudo_filename"] == "Ultrassom SID,Rosa.pdf"
    assert result["exame"]["arquivo_status"] == "caminho_local_ignorado"


def test_mcp_open_laudo_widget_strips_unreachable_chatgpt_local_path(app, client):
    with app.app_context():
        professional = User(
            name="Dra. Widget Local",
            email="widget-local-laudo@example.com",
            role="veterinario",
            worker="veterinario",
        )
        professional.set_password("secret123")
        db.session.add(professional)
        db.session.flush()
        db.session.add(Veterinario(user_id=professional.id, crmv="CRMV-WIDGET"))
        db.session.commit()
        token_value = _create_token(professional.id, scope="profile")

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 431,
            "method": "tools/call",
            "params": {
                "name": "abrir_importador_laudo_volante",
                "arguments": {
                    "clinica": {"nome": "Clinica Local Path"},
                    "tutor": {"nome": "Tutor Local"},
                    "animal": {"nome": "SID", "especie": "canina"},
                    "exame": {"nome": "Ultrassom"},
                    "laudo_url": "/mnt/data/Ultrassom SID,Rosa.pdf",
                    "laudo_filename": "Ultrassom SID,Rosa.pdf",
                },
            },
        },
    )

    assert response.status_code == 200
    draft = response.get_json()["result"]["structuredContent"]["rascunho"]
    assert draft["laudo_url"] == ""
    assert draft["laudo_filename"] == "Ultrassom SID,Rosa.pdf"


def test_mcp_sugerir_modelo_laudo_uses_previous_reports(app, client):
    with app.app_context():
        professional = User(name="Dra. Modelo", email="modelo-laudo@example.com", role="veterinario", worker="veterinario")
        professional.set_password("secret123")
        tutor = User(name="Tutor Modelo", email="tutor-modelo@example.com")
        tutor.set_password("secret123")
        animal = Animal(name="Paciente Modelo", owner=tutor)
        db.session.add_all([professional, tutor, animal])
        db.session.flush()
        db.session.add(Veterinario(user_id=professional.id, crmv="CRMV-MODELO"))
        bloco = BlocoExames(animal=animal)
        db.session.add(ExameSolicitado(
            bloco=bloco,
            nome="Ultrassonografia abdominal",
            status="concluido",
            resultado="Bexiga com paredes espessadas. Impressao diagnostica: cistite.",
            performed_at=datetime(2026, 2, 16),
        ))
        db.session.commit()
        token_value = _create_token(professional.id, scope="profile")

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 44,
            "method": "tools/call",
            "params": {
                "name": "sugerir_modelo_laudo",
                "arguments": {"tipo_exame": "Ultrassonografia abdominal", "achados": "Bexiga espessada."},
            },
        },
    )

    assert response.status_code == 200
    result = json.loads(response.get_json()["result"]["content"][0]["text"])
    assert result["tipo_exame"] == "Ultrassonografia abdominal"
    assert "Bexiga espessada." in result["rascunho_base"]
    assert result["exemplos_encontrados"][0]["trecho_modelo"].startswith("Bexiga")


def test_mcp_store_tools_search_products_and_create_order(app, client):
    with app.app_context():
        tutor = User(name="Cliente Loja", email="cliente-loja-mcp@example.com", role="adotante")
        tutor.set_password("secret123")
        product = Product(
            name="Premier Formula Adulto Raças Grandes 15 kg",
            description="Ração seca para cães adultos de raças grandes.",
            price=180.00,
            stock=8,
            category="racao",
            status="active",
        )
        db.session.add_all([tutor, product])
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id,
            name="Saco 15 kg",
            weight_volume="15 kg",
            price=180.00,
            stock=8,
            status="active",
        )
        db.session.add(variant)
        db.session.commit()
        token_value = _create_token(tutor.id, scope="profile")
        tutor_id = tutor.id
        product_id = product.id
        variant_id = variant.id

    headers = {"Authorization": f"Bearer {token_value}"}
    tools_response = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 70, "method": "tools/list", "params": {}},
    )
    tool_names = {tool["name"] for tool in tools_response.get_json()["result"]["tools"]}
    assert {"buscar_produtos_loja", "obter_produto_loja", "criar_pedido_loja"}.issubset(tool_names)

    search_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 71,
            "method": "tools/call",
            "params": {"name": "buscar_produtos_loja", "arguments": {"termo": "Premier 15 kg"}},
        },
    )
    search_payload = json.loads(search_response.get_json()["result"]["content"][0]["text"])
    assert search_payload["total"] == 1
    assert search_payload["produtos"][0]["id"] == product_id
    assert "Premier Formula" in search_payload["produtos"][0]["nome"]

    detail_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 72,
            "method": "tools/call",
            "params": {"name": "obter_produto_loja", "arguments": {"produto_id": product_id}},
        },
    )
    detail_payload = json.loads(detail_response.get_json()["result"]["content"][0]["text"])
    assert detail_payload["produto"]["variantes"][0]["id"] == variant_id

    order_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 73,
            "method": "tools/call",
            "params": {
                "name": "criar_pedido_loja",
                "arguments": {
                    "itens": [{"produto_id": product_id, "variante_id": variant_id, "quantidade": 1}],
                    "endereco_entrega": "Rua Teste, 123",
                    "confirmar_gravacao": "sim",
                },
            },
        },
    )
    order_payload = order_response.get_json()["result"]["structuredContent"]
    assert order_payload["success"] is True
    assert order_payload["pagamento_no_chatgpt"] is False
    assert "/carrinho/retomar/" in order_payload["pedido"]["url_carrinho"]
    with app.app_context():
        order = db.session.get(Order, order_payload["pedido"]["id"])
        assert order is not None
        assert order.user_id == tutor_id
        assert order.items[0].variant_id == variant_id


def test_mcp_laudo_volante_widget_contract(app, client):
    with app.app_context():
        professional = User(
            name="Dra. Widget",
            email="widget-laudo@example.com",
            role="veterinario",
            worker="veterinario",
        )
        professional.set_password("secret123")
        db.session.add(professional)
        db.session.flush()
        db.session.add(Veterinario(user_id=professional.id, crmv="CRMV-WIDGET"))
        db.session.commit()

        token_value = _create_token(
            professional.id,
            scope="profile tutors:write pets:write exams:write exams:read clinical_summary:read",
        )

    headers = {"Authorization": f"Bearer {token_value}"}

    initialize = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 51, "method": "initialize", "params": {}},
    )
    assert initialize.status_code == 200
    assert "resources" in initialize.get_json()["result"]["capabilities"]

    current_protocol = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 511,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
    )
    assert current_protocol.status_code == 200
    assert current_protocol.get_json()["result"]["protocolVersion"] == "2025-06-18"

    tools_response = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 52, "method": "tools/list", "params": {}},
    )
    tools = tools_response.get_json()["result"]["tools"]
    assert tools
    tool_names = {tool["name"] for tool in tools}
    expected_widget_tools = {
        "criar_exame_imagem",
        "anexar_pdf_exame_imagem",
        "liberar_exame_para_clinica",
        "liberar_exame_para_tutor",
        "gerar_convite_primeiro_acesso_clinica",
        "gerar_convite_acesso_tutor",
        "listar_historico_medico_animal",
        "obter_documento_clinico",
        "buscar_ou_criar_clinica_requisitante",
        "buscar_ou_criar_tutor_animal",
    }
    assert expected_widget_tools.issubset(tool_names), expected_widget_tools - tool_names
    for tool in tools:
        annotations = tool.get("annotations") or {}
        assert isinstance(annotations.get("readOnlyHint"), bool), tool["name"]
        assert isinstance(annotations.get("destructiveHint"), bool), tool["name"]
        assert isinstance(annotations.get("openWorldHint"), bool), tool["name"]
        assert tool.get("outputSchema", {}).get("type") == "object", tool["name"]
        if tool["name"] in {
            "listar_meus_pets",
            "listar_agendamentos",
            "interpretar_mensagem_livre_atendimento",
            "assistente_operacional_veterinario",
            "cadastrar_tutor_e_pets",
            "registrar_consulta_clinica",
            "registrar_bloco_exames",
            "criar_exame_imagem",
            "anexar_pdf_exame_imagem",
            "liberar_exame_para_clinica",
            "liberar_exame_para_tutor",
            "gerar_convite_primeiro_acesso_clinica",
            "gerar_convite_acesso_tutor",
            "listar_historico_medico_animal",
            "obter_documento_clinico",
            "buscar_ou_criar_clinica_requisitante",
            "buscar_ou_criar_tutor_animal",
            "abrir_importador_laudo_volante",
            "importar_laudo_volante",
            "agendar_consulta",
            "agendar_retorno",
            "obter_resumo_clinico_animal",
            "listar_agenda_do_dia",
            "listar_pendencias_clinicas",
            "listar_vacinas_pendentes",
            "listar_exames_pendentes",
            "listar_retornos_pendentes",
            "gerar_orientacao_tutor",
            "gerar_handoff_clinico",
        }:
            assert tool.get("securitySchemes"), tool["name"]
            assert tool.get("_meta", {}).get("securitySchemes"), tool["name"]
    history_tool = next(tool for tool in tools if tool["name"] == "listar_historico_medico_animal")
    assert "shareable_url" in history_tool["description"]
    assert "bearer" in history_tool["description"]
    document_tool = next(tool for tool in tools if tool["name"] == "obter_documento_clinico")
    assert "shareable_url" in document_tool["description"]
    assert "URL de API protegida" in document_tool["description"]
    pdf_tool = next(tool for tool in tools if tool["name"] == "anexar_pdf_exame_imagem")
    assert pdf_tool["_meta"]["openai/fileParams"] == ["arquivo_pdf"]
    assert "attachment_id" not in (pdf_tool["inputSchema"].get("required") or [])
    assert pdf_tool["inputSchema"]["properties"]["arquivo_pdf"]["required"] == ["download_url", "file_id"]
    render_tool = next(tool for tool in tools if tool["name"] == "abrir_importador_laudo_volante")
    assert "ui" not in render_tool["_meta"]
    assert "openai/outputTemplate" not in render_tool["_meta"]
    assert render_tool["_meta"]["openai/fileParams"] == ["laudo_arquivo"]
    assert render_tool["inputSchema"]["properties"]["laudo_arquivo"]["required"] == ["download_url", "file_id"]
    assert "mensagem_tutor" in render_tool["inputSchema"]["properties"]
    import_tool = next(tool for tool in tools if tool["name"] == "importar_laudo_volante")
    assert import_tool["_meta"]["openai/fileParams"] == ["laudo_arquivo"]
    assert import_tool["outputSchema"]["properties"]["exame"]["type"] == "object"
    assert import_tool["outputSchema"]["properties"]["comunicacao"]["type"] == "object"
    assert render_tool["annotations"]["readOnlyHint"] is True

    resource_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 53,
            "method": "resources/read",
            "params": {"uri": "ui://petorlandia/laudo-volante-v2.html"},
        },
    )
    resource = resource_response.get_json()["result"]["contents"][0]
    assert resource["mimeType"] == "text/html;profile=mcp-app"
    assert 'window.openai.callTool("importar_laudo_volante"' in resource["text"]
    assert 'window.openai.selectFiles' in resource["text"]
    assert 'window.openai.uploadFile' in resource["text"]
    assert "Enviar WhatsApp" in resource["text"]
    assert "mensagem_tutor" in resource["text"]
    assert "window.openai?.openExternal" in resource["text"]
    assert "https://wa.me" in resource["_meta"]["openai/widgetCSP"]["redirect_domains"]

    render_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 54,
            "method": "tools/call",
            "params": {
                "name": "abrir_importador_laudo_volante",
                "arguments": {
                    "clinica": {"nome": "Clinica Visual"},
                    "tutor": {"nome": "Tutor Visual"},
                    "animal": {"nome": "Nina", "especie": "felina"},
                    "exame": {"nome": "Ultrassonografia abdominal"},
                    "laudo_texto": "Achados sem alteracoes relevantes.",
                    "campos_a_confirmar": ["telefone do tutor"],
                },
            },
        },
    )
    render_payload = render_response.get_json()["result"]
    assert render_payload["structuredContent"]["rascunho"]["animal"]["nome"] == "Nina"
    assert render_payload["structuredContent"]["campos_a_confirmar"] == ["telefone do tutor"]
    assert "_meta" not in render_payload


def test_mcp_operational_widget_resources_are_available(app, client):
    with app.app_context():
        admin = User(name="Admin ChatGPT", email="admin-mcp-widgets@example.com", role="admin")
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()
        token_value = _create_token(admin.id, scope="profile appointments:read clinical_summary:read exams:read vaccines:read")

    headers = {"Authorization": f"Bearer {token_value}"}
    resources_response = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 80, "method": "resources/list", "params": {}},
    )
    resources = resources_response.get_json()["result"]["resources"]
    uris = {resource["uri"] for resource in resources}
    assert {
        "ui://petorlandia/laudo-volante-v2.html",
        "ui://petorlandia/agenda-cockpit-v1.html",
        "ui://petorlandia/timeline-clinica-v1.html",
        "ui://petorlandia/admin-command-center-v1.html",
    }.issubset(uris)

    for uri in (
        "ui://petorlandia/agenda-cockpit-v1.html",
        "ui://petorlandia/timeline-clinica-v1.html",
        "ui://petorlandia/admin-command-center-v1.html",
    ):
        resource_response = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 81, "method": "resources/read", "params": {"uri": uri}},
        )
        resource = resource_response.get_json()["result"]["contents"][0]
        assert resource["mimeType"] == "text/html;profile=mcp-app"
        assert "window.openai" in resource["text"]
        assert resource["_meta"]["openai/widgetDescription"]


def test_mcp_admin_alert_tools_list_and_resolve(app, client):
    with app.app_context():
        admin = User(name="Admin MCP", email="admin-mcp-alerts@example.com", role="admin")
        admin.set_password("secret123")
        vet = User(name="Vet MCP", email="vet-mcp-alerts@example.com", role="veterinario", worker="veterinario")
        vet.set_password("secret123")
        db.session.add_all([admin, vet])
        db.session.flush()
        note = AdminActionNotification(
            recipient_user_id=admin.id,
            event_type="career_application",
            entity_type="petsitter_application",
            entity_id=42,
            title="Nova candidatura petsitter",
            body="Uma candidata enviou formulario de carreira.",
            url="/admin/carreiras",
            priority="high",
            status="unread",
            idempotency_key="test:mcp-admin-alert",
        )
        db.session.add(note)
        db.session.commit()
        admin_token = _create_token(admin.id, scope="profile")
        vet_token = _create_token(vet.id, scope="profile")
        note_id = note.id

    vet_tools_response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {vet_token}"},
        json={"jsonrpc": "2.0", "id": 82, "method": "tools/list", "params": {}},
    )
    vet_tool_names = {tool["name"] for tool in vet_tools_response.get_json()["result"]["tools"]}
    assert "listar_alertas_admin" not in vet_tool_names
    assert "resolver_alerta_admin" not in vet_tool_names

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    admin_tools_response = client.post(
        "/mcp",
        headers=admin_headers,
        json={"jsonrpc": "2.0", "id": 83, "method": "tools/list", "params": {}},
    )
    admin_tool_names = {tool["name"] for tool in admin_tools_response.get_json()["result"]["tools"]}
    assert {"listar_alertas_admin", "resolver_alerta_admin"}.issubset(admin_tool_names)

    list_response = client.post(
        "/mcp",
        headers=admin_headers,
        json={
            "jsonrpc": "2.0",
            "id": 84,
            "method": "tools/call",
            "params": {"name": "listar_alertas_admin", "arguments": {"status": "open"}},
        },
    )
    result = list_response.get_json()["result"]
    assert "_meta" not in result
    payload = json.loads(result["content"][0]["text"])
    assert payload["total_abertos"] == 1
    assert payload["alertas"][0]["titulo"] == "Nova candidatura petsitter"

    resolve_response = client.post(
        "/mcp",
        headers=admin_headers,
        json={
            "jsonrpc": "2.0",
            "id": 85,
            "method": "tools/call",
            "params": {
                "name": "resolver_alerta_admin",
                "arguments": {"alerta_id": note_id, "acao": "resolver", "confirmar_gravacao": "sim"},
            },
        },
    )
    assert resolve_response.get_json()["result"]["structuredContent"]["alerta"]["status"] == "resolved"


def test_mcp_carteirinha_photo_review_and_import(app, client):
    with app.app_context():
        tutor = User(name="Juliana", email="juliana-carteirinha@example.com", role="adotante")
        tutor.set_password("secret123")
        db.session.add(tutor)
        db.session.flush()
        pet = Animal(name="Durga", user_id=tutor.id, status="disponivel", modo="adotado")
        db.session.add(pet)
        db.session.commit()
        pet_id = pet.id
        token_value = _create_token(tutor.id, scope="profile pets:read pets:write")

    extracted = {
        "pet": {
            "nome": "Durga",
            "sexo": "F",
            "data_nascimento": "2016-04-20",
            "pelagem": "azul com branco",
        },
        "vacinas": [
            {
                "nome": "Nobivac DHPPi+L",
                "aplicada_em": "2024-09-28",
                "proxima_dose": "2025-09-28",
                "fabricante": "MSD",
                "lote": "033/23",
                "confianca": "alta",
            },
            {
                "nome": "Canigen R",
                "aplicada_em": "2024-09-28",
                "proxima_dose": "2025-09-28",
                "confianca": "baixa",
            },
        ],
        "vermifugacoes": [
            {
                "medicamento": "Canex",
                "data": "2024-11-07",
                "proxima_dose": "2024-11-22",
                "peso_kg": "8,1",
                "confianca": "alta",
            },
        ],
    }
    headers = _auth_header(token_value)
    tools_response = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 89, "method": "tools/list", "params": {}},
    )
    tools_by_name = {tool["name"]: tool for tool in tools_response.get_json()["result"]["tools"]}
    assert {"revisar_carteirinha_fotografada", "importar_carteirinha_fotografada"}.issubset(tools_by_name)
    assert tools_by_name["importar_carteirinha_fotografada"]["_meta"]["openai/fileParams"] == ["fotos_carteirinha"]

    review = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 90,
            "method": "tools/call",
            "params": {
                "name": "revisar_carteirinha_fotografada",
                "arguments": {"animal_id": pet_id, "dados_extraidos": extracted},
            },
        },
    )
    assert review.status_code == 200
    review_payload = review.get_json()["result"]["structuredContent"]
    assert review_payload["animal_encontrado"]["nome"] == "Durga"
    assert len(review_payload["itens_de_baixa_confianca"]) == 1

    imported = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 91,
            "method": "tools/call",
            "params": {
                "name": "importar_carteirinha_fotografada",
                "arguments": {
                    "animal_id": pet_id,
                    "dados_extraidos": extracted,
                    "confirmar_gravacao": "sim",
                },
            },
        },
    )
    assert imported.status_code == 200
    imported_payload = imported.get_json()["result"]["structuredContent"]
    assert imported_payload["vacinas_importadas"] == 1
    assert imported_payload["vermifugacoes_importadas"] == 1

    with app.app_context():
        pet = db.session.get(Animal, pet_id)
        assert pet.sex == "F"
        assert pet.date_of_birth == date(2016, 4, 20)
        assert "Pelagem informada" in pet.description
        assert Vacina.query.filter_by(animal_id=pet_id).count() == 1
        assert AnimalHealthRecord.query.filter_by(animal_id=pet_id, kind="vermifugacao").count() == 1
        assert CarteirinhaImportacao.query.filter_by(animal_id=pet_id, user_id=pet.user_id).count() == 1


def test_mcp_registration_tool_creates_and_reuses_tutor_and_pets(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica ChatGPT")
        db.session.add(clinic)
        db.session.flush()
        clinic_id = clinic.id

        professional = User(
            name="Dra. Marina",
            email="marina-chatgpt@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        professional.set_password("secret123")
        db.session.add(professional)
        db.session.flush()

        db.session.add(
            Veterinario(
                user_id=professional.id,
                crmv="CRMV-2026",
            )
        )
        db.session.commit()

        token_value = _create_token(
            professional.id,
            scope="profile tutors:write pets:write pets:read appointments:read",
        )

    request_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "cadastrar_tutor_e_pets",
            "arguments": {
                "confirmar_gravacao": "sim",
                "tutor": {
                    "nome": "Nelson Benedito",
                    "telefone": "99344-5088",
                    "endereco": "Travessa V, 1211 - CEP 14620-000",
                },
                "pets": [
                    {"nome": "Marron", "especie": "cao", "idade": "2 anos"},
                    {"nome": "Tigrinho", "especie": "cão", "idade": "2 anos"},
                ],
                "observacao_clinica": "Problema ocular com aspecto azulado. Alimentação normal.",
                "disponibilidade": "Qualquer horário (preferência: 12/11 entre 14h e 16h)",
            },
        },
    }

    first_response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json=request_payload,
    )
    assert first_response.status_code == 200
    first_payload = first_response.get_json()
    first_result = json.loads(first_payload["result"]["content"][0]["text"])

    assert first_result["tutor"]["ja_existia"] is False
    assert first_result["tutor"]["email_provisorio"] is True
    assert first_result["resumo"]["pets_criados"] == 2
    assert first_result["resumo"]["consultas_iniciais_criadas"] == 2

    with app.app_context():
        tutor = User.query.filter_by(name="Nelson Benedito").one()
        assert tutor.clinica_id == clinic_id
        assert tutor.address == "Travessa V, 1211 - CEP 14620-000"
        assert tutor.email.endswith("@cadastro.petorlandia.local")

        pets = Animal.query.filter_by(user_id=tutor.id).order_by(Animal.name).all()
        assert [pet.name for pet in pets] == ["Marron", "Tigrinho"]
        assert all(pet.species and pet.species.name == "Cachorro" for pet in pets)

        consultas = Consulta.query.filter(Consulta.animal_id.in_([pet.id for pet in pets])).all()
        assert len(consultas) == 2
        assert all(
            consulta.queixa_principal == "Problema ocular com aspecto azulado. Alimentação normal."
            for consulta in consultas
        )
        assert all(
            "Disponibilidade informada: Qualquer horário (preferência: 12/11 entre 14h e 16h)"
            in (consulta.historico_clinico or "")
            for consulta in consultas
        )

    second_response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json=request_payload,
    )
    assert second_response.status_code == 200
    second_payload = second_response.get_json()
    second_result = json.loads(second_payload["result"]["content"][0]["text"])

    assert second_result["tutor"]["ja_existia"] is True
    assert all(pet["ja_existia"] is True for pet in second_result["pets"])
    assert second_result["resumo"]["pets_criados"] == 0
    assert second_result["resumo"]["pets_reaproveitados"] == 2

    with app.app_context():
        assert User.query.filter_by(name="Nelson Benedito").count() == 1
        tutor = User.query.filter_by(name="Nelson Benedito").one()
        assert Animal.query.filter_by(user_id=tutor.id).count() == 2
        assert Consulta.query.count() == 2
