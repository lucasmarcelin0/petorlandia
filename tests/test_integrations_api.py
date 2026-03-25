import json
from datetime import timedelta

from extensions import db
from models import Animal, Appointment, Clinica, Consulta, OAuthAccessToken, User, Veterinario
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


def test_mcp_registration_tool_creates_and_reuses_tutor_and_pets(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica ChatGPT")
        db.session.add(clinic)
        db.session.flush()

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
        assert tutor.clinica_id == clinic.id
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
