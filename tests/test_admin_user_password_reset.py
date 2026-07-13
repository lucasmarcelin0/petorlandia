"""Redefinição de senha de usuário pelo admin (Flask-Admin /painel/user/edit)."""

from extensions import db
from models import User


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _setup_admin_and_target(app):
    with app.app_context():
        admin = User(
            name='Admin da Plataforma',
            email='admin-reset-senha@example.test',
            role='admin',
        )
        admin.set_password('senha-admin')
        target = User(
            name='Usuário que perdeu a senha',
            email='usuario-reset-senha@example.test',
        )
        target.set_password('senha-antiga')
        db.session.add_all([admin, target])
        db.session.commit()
        return admin.id, target.id


def test_admin_can_reset_user_password(client, app):
    admin_id, target_id = _setup_admin_and_target(app)
    _login(client, admin_id)

    response = client.post(
        f'/painel/user/edit/?id={target_id}',
        data={
            'name': 'Usuário que perdeu a senha',
            'email': 'usuario-reset-senha@example.test',
            'new_password': 'senha-nova-123',
            'role': 'adotante',
            'worker': '',
        },
    )
    assert response.status_code == 302

    with app.app_context():
        target = db.session.get(User, target_id)
        assert target.check_password('senha-nova-123')
        assert not target.check_password('senha-antiga')


def test_blank_password_field_keeps_current_password(client, app):
    admin_id, target_id = _setup_admin_and_target(app)
    _login(client, admin_id)

    response = client.post(
        f'/painel/user/edit/?id={target_id}',
        data={
            'name': 'Nome Atualizado',
            'email': 'usuario-reset-senha@example.test',
            'new_password': '',
            'role': 'adotante',
            'worker': '',
        },
    )
    assert response.status_code == 302

    with app.app_context():
        target = db.session.get(User, target_id)
        assert target.name == 'Nome Atualizado'
        assert target.check_password('senha-antiga')


def test_short_password_is_rejected(client, app):
    admin_id, target_id = _setup_admin_and_target(app)
    _login(client, admin_id)

    response = client.post(
        f'/painel/user/edit/?id={target_id}',
        data={
            'name': 'Usuário que perdeu a senha',
            'email': 'usuario-reset-senha@example.test',
            'new_password': '123',
            'role': 'adotante',
            'worker': '',
        },
    )
    # Flask-Admin devolve o formulário (200) com o erro em flash
    assert response.status_code == 200

    with app.app_context():
        target = db.session.get(User, target_id)
        assert target.check_password('senha-antiga')
