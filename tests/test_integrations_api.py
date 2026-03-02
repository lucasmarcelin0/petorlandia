from datetime import timedelta

from extensions import db
from models import Animal, Appointment, OAuthAccessToken, User, Veterinario
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
