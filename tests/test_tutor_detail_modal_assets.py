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
