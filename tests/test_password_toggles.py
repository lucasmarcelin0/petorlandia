from bs4 import BeautifulSoup
from extensions import db
from models import User


def test_password_toggle_on_change_password_page(client, app):
    """Garante que a página de alteração de senha contém botões acessíveis de visibilidade de senha."""
    with app.app_context():
        user = User(name="User Password Test", email="user-pwd@test.com")
        user.set_password("senha123")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True

    response = client.get("/change_password")
    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")

    toggles = soup.select("[data-password-toggle]")
    assert len(toggles) == 3, "Esperado 3 alternadores de senha na página de alteração de senha"

    for toggle in toggles:
        assert toggle.get("aria-label") == "Mostrar senha"
        assert toggle.get("aria-pressed") == "false"
        assert toggle.get("aria-controls") in ["current_password", "new_password", "confirm_password"]


def test_password_toggle_on_reset_password_page(client, app):
    """Garante que a página de redefinição de senha contém botões acessíveis de visibilidade de senha."""
    with app.app_context():
        from itsdangerous import URLSafeTimedSerializer
        s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
        user = User(name="User Reset Test", email="user-reset@test.com")
        user.set_password("senha123")
        db.session.add(user)
        db.session.commit()
        token = s.dumps(user.email, salt='password-reset-salt')

    response = client.get(f"/reset_password/{token}")
    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")

    toggles = soup.select("[data-password-toggle]")
    assert len(toggles) == 2, "Esperado 2 alternadores de senha na página de redefinição de senha"

    for toggle in toggles:
        assert toggle.get("aria-label") == "Mostrar senha"
        assert toggle.get("aria-pressed") == "false"
        assert toggle.get("aria-controls") in ["password", "confirm_password"]
