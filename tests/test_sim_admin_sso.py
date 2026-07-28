from models.usuarios import User

from blueprints.sim import SimSession, SimUser, now_iso
from extensions import db


def _log_in(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_petorlandia_admin_opens_sim_without_a_second_login(app):
    with app.app_context():
        admin = User(
            name="Admin do PetOrlandia",
            email="admin-sim@example.test",
            password_hash="unused",
            role="admin",
        )
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    client = app.test_client()
    _log_in(client, admin_id)

    session_response = client.get("/sim/api/session")
    assert session_response.status_code == 200
    assert session_response.get_json()["user"] == {
        "email": "admin-sim@example.test",
        "name": admin.name,
        "role": "sim",
    }
    assert client.get("/sim/api/state").status_code == 200
    assert client.get("/sim/api/registry").status_code == 200

    with app.app_context():
        assert SimUser.query.filter_by(email="admin-sim@example.test", role="sim").count() == 1


def test_non_admin_petorlandia_user_does_not_gain_sim_access(app):
    with app.app_context():
        user = User(
            name="Usuario comum",
            email="user-sim@example.test",
            password_hash="unused",
            role="tutor",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _log_in(client, user_id)

    assert client.get("/sim/api/session").get_json() == {"user": None}
    assert client.get("/sim/api/state").status_code == 401


def test_sim_admin_can_list_accounts_without_sensitive_credentials(app):
    with app.app_context():
        admin = User(name="Admin", email="admin-accounts@example.test", password_hash="unused", role="admin")
        establishment = SimUser(
            name="Estabelecimento de teste",
            email="estabelecimento@example.test",
            role="establishment",
            password_hash="unused",
            created_at="2026-07-27T10:00:00-03:00",
        )
        db.session.add_all([admin, establishment])
        db.session.flush()
        db.session.add(SimSession(
            token="session-for-account-list",
            user_id=establishment.id,
            created_at=now_iso(),
            last_seen_at="2026-07-28T09:00:00-03:00",
        ))
        db.session.commit()
        admin_id = admin.id

    client = app.test_client()
    _log_in(client, admin_id)
    response = client.get("/sim/api/registry")

    assert response.status_code == 200
    accounts = response.get_json()["registry"]["accounts"]
    account = next(item for item in accounts if item["email"] == "estabelecimento@example.test")
    assert account == {
        "id": account["id"],
        "name": "Estabelecimento de teste",
        "email": "estabelecimento@example.test",
        "role": "establishment",
        "active": True,
        "created_at": "2026-07-27T10:00:00-03:00",
        "last_seen_at": "2026-07-28T09:00:00-03:00",
    }
    assert "password_hash" not in account
    assert "token" not in account
