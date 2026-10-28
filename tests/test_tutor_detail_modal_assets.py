from bs4 import BeautifulSoup

from extensions import db
from models import Clinica, User


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess.clear()
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_ficha_tutor_does_not_load_bootstrap_bundle_twice(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica Teste")
        db.session.add(clinic)
        db.session.flush()

        admin = User(
            name="Admin",
            email="admin-tutor-detail@test",
            password_hash="x",
            role="admin",
            clinica_id=clinic.id,
        )
        tutor = User(
            name="Tutor Teste",
            email="tutor-detail@test",
            password_hash="x",
            clinica_id=clinic.id,
        )
        db.session.add_all([admin, tutor])
        db.session.commit()
        admin_id = admin.id
        tutor_id = tutor.id

    _login(client, admin_id)
    response = client.get(f"/ficha_tutor/{tutor_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js" not in html
    assert html.count("bootstrap.bundle.min.js") == 1
    assert html.count("js/destructive_actions.js") == 1
    assert html.count("css/destructive_actions.css") == 1
    soup = BeautifulSoup(html, "html.parser")
    danger = soup.select_one(".tutor-perigo")
    disclosure = danger.find_parent("details")
    assert disclosure is not None
    assert not disclosure.has_attr("open")
    assert "Mais opções" in disclosure.summary.get_text()
    assert danger.select_one('input[name="csrf_token"]') is not None
    assert "confirm(" in danger.form["onsubmit"]
    assert soup.select_one('[data-confirmar-remocao][data-destructive-confirmation]') is not None
