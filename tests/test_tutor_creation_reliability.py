from __future__ import annotations

from extensions import db
from models import User, Veterinario


def _create_professional(app) -> int:
    with app.app_context():
        professional = User(
            name="Dra. Cadastro",
            email="cadastro.vet@example.com",
            worker="veterinario",
        )
        professional.set_password("senha-segura")
        professional.veterinario = Veterinario(crmv="CRMV-RELIABILITY")
        db.session.add(professional)
        db.session.commit()
        return professional.id


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_tutor_form_has_visible_feedback_and_explicit_submit(app, client):
    professional_id = _create_professional(app)
    _login(client, professional_id)

    response = client.get("/tutores?scope=all&tutor_sort=date_desc&panel=cadastro")

    assert response.status_code == 200
    assert b'form-status-message alert d-none' in response.data
    assert b'<button type="submit" class="btn btn-success' in response.data


def test_tutor_creation_returns_consistent_json_and_random_password(app, client):
    professional_id = _create_professional(app)
    _login(client, professional_id)

    response = client.post(
        "/tutores?scope=all&tutor_sort=date_desc&panel=cadastro",
        data={"name": "  Maria Confiável  ", "email": "MARIA@EXAMPLE.COM"},
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["tutor"]["name"] == "Maria Confiável"

    with app.app_context():
        tutor = User.query.filter_by(email="maria@example.com").one()
        assert tutor.check_password("123456789") is False


def test_tutor_creation_reports_validation_and_uniqueness_errors(app, client):
    professional_id = _create_professional(app)
    with app.app_context():
        existing = User(name="Tutor Existente", email="existente@example.com", cpf="111.222.333-44")
        existing.set_password("senha")
        db.session.add(existing)
        db.session.commit()
    _login(client, professional_id)

    headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}

    missing_name = client.post("/tutores", data={"name": ""}, headers=headers)
    assert missing_name.status_code == 400
    assert missing_name.get_json() == {
        "success": False,
        "message": "Informe o nome do tutor.",
        "category": "warning",
    }

    duplicate_email = client.post(
        "/tutores",
        data={"name": "Outro", "email": "EXISTENTE@EXAMPLE.COM"},
        headers=headers,
    )
    assert duplicate_email.status_code == 409
    assert duplicate_email.get_json()["success"] is False

    duplicate_cpf = client.post(
        "/tutores",
        data={"name": "Outro", "cpf": "111.222.333-44"},
        headers=headers,
    )
    assert duplicate_cpf.status_code == 409
    assert duplicate_cpf.get_json()["message"] == "CPF já cadastrado para outro tutor."

