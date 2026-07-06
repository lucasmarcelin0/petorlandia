from extensions import db
from models import Animal, User


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_admin_can_follow_tutor_links_for_animal_without_clinic(app, client):
    with app.app_context():
        admin = User(
            name='Admin Animal',
            email='admin-animal@test',
            password_hash='x',
            role='admin',
        )
        tutor = User(
            name='Tutor Animal',
            email='tutor-animal@test',
            password_hash='x',
        )
        db.session.add_all([admin, tutor])
        db.session.flush()
        animal = Animal(
            name='Duds Regression',
            user_id=tutor.id,
            clinica_id=None,
            added_by_id=None,
            modo='adotado',
            status='disponível',
        )
        db.session.add(animal)
        db.session.commit()
        admin_id = admin.id
        tutor_id = tutor.id
        animal_id = animal.id

    _login(client, admin_id)

    tutor_response = client.get(f'/ficha_tutor/{tutor_id}')
    assert tutor_response.status_code == 200
    assert f'/animal/{animal_id}/ficha'.encode() in tutor_response.data

    assert client.get(f'/animal/{animal_id}/ficha').status_code == 200
    assert client.get(f'/animal/{animal_id}/ficha?section=events').status_code == 200
    assert client.get(f'/animal/{animal_id}/ficha?section=history').status_code == 200
