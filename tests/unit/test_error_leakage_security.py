from unittest.mock import patch
from models import Animal, User, Veterinario
from extensions import db


def test_delete_tutor_does_not_leak_exception_details(app, client):
    """Garante que falhas no deletar_tutor não vazam a exceção crua ao usuário."""
    with app.app_context():
        admin = User(name="Admin Vet", email="admin_vet_leak@test.com", role="admin", worker="veterinario")
        admin.set_password("pass123")
        vet_profile = Veterinario(user=admin, crmv="12345")
        tutor = User(name="Tutor Test", email="tutor_leak@test.com", role="adotante")
        tutor.set_password("pass123")
        db.session.add_all([admin, vet_profile, tutor])
        db.session.commit()
        admin_id = admin.id
        tutor_id = tutor.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)

    with patch.object(db.session, "commit", side_effect=RuntimeError("SECRET_DB_CONSTRAINT_ERROR_12345")):
        response = client.post(f"/deletar_tutor/{tutor_id}", follow_redirects=True)
        assert response.status_code == 200
        content = response.get_data(as_text=True)
        assert "SECRET_DB_CONSTRAINT_ERROR_12345" not in content
        assert "Não foi possível excluir o tutor" in content


def test_marcar_falecido_does_not_leak_exception_details(app, client):
    """Garante que falhas no marcar_falecido não vazam a exceção crua ao usuário."""
    with app.app_context():
        vet = User(name="Vet Test", email="vet_leak@test.com", role="admin", worker="veterinario")
        vet.set_password("pass123")
        vet_profile = Veterinario(user=vet, crmv="12346")
        tutor = User(name="Tutor Test 2", email="tutor_leak2@test.com", role="adotante")
        tutor.set_password("pass123")
        animal = Animal(name="Rex Leak", owner=tutor, is_alive=True)
        db.session.add_all([vet, vet_profile, tutor, animal])
        db.session.commit()
        vet_id = vet.id
        animal_id = animal.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(vet_id)

    with patch.object(db.session, "commit", side_effect=RuntimeError("SECRET_DB_CONSTRAINT_ERROR_67890")):
        response = client.post(
            f"/animal/{animal_id}/marcar_falecido",
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 400
        json_data = response.get_json()
        assert "SECRET_DB_CONSTRAINT_ERROR_67890" not in json_data["message"]
        assert "Não foi possível marcar como falecido." in json_data["message"]


def test_arquivar_animal_does_not_leak_exception_details(app, client):
    """Garante que falhas no arquivar_animal não vazam a exceção crua ao usuário."""
    with app.app_context():
        vet = User(name="Vet Test 3", email="vet_leak3@test.com", role="admin", worker="veterinario")
        vet.set_password("pass123")
        vet_profile = Veterinario(user=vet, crmv="12347")
        tutor = User(name="Tutor Test 3", email="tutor_leak3@test.com", role="adotante")
        tutor.set_password("pass123")
        animal = Animal(name="Bob Leak", owner=tutor, is_alive=True)
        db.session.add_all([vet, vet_profile, tutor, animal])
        db.session.commit()
        vet_id = vet.id
        animal_id = animal.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(vet_id)

    with patch.object(db.session, "commit", side_effect=RuntimeError("SECRET_DB_CONSTRAINT_ERROR_99999")):
        response = client.post(
            f"/animal/{animal_id}/arquivar",
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 400
        json_data = response.get_json()
        assert "SECRET_DB_CONSTRAINT_ERROR_99999" not in json_data["message"]
        assert "Não foi possível excluir o animal." in json_data["message"]
