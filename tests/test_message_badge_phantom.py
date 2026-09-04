"""Badge de mensagens: contar so o que a caixa de entrada consegue mostrar.

Regressao da "notificacao fantasma" no admin: a navbar acusava mensagem nova
e /mensagens_admin nao tinha nenhuma conversa com badge para abrir.
"""
import flask_login.utils as login_utils

from context_processors import inject_unread_count
from extensions import db
from models import Message, User


def _make_users():
    admin = User(id=1, name='Admin', email='admin@test.com', password_hash='x', role='admin')
    outro_admin = User(id=2, name='Admin 2', email='admin2@test.com', password_hash='x', role='Admin')
    tutor = User(id=3, name='Tutor', email='tutor@test.com', password_hash='x', role='adotante')
    db.session.add_all([admin, outro_admin, tutor])
    db.session.commit()
    return admin, outro_admin, tutor


def test_mensagem_entre_admins_nao_acende_o_badge(monkeypatch, app):
    """A listagem do admin descarta mensagens de remetente admin.

    Enquanto o badge as contava, sobrava uma notificacao que nao levava a
    conversa nenhuma — e nenhuma leitura conseguia apaga-la.
    """
    with app.app_context():
        admin, outro_admin, _ = _make_users()
        db.session.add(
            Message(sender_id=outro_admin.id, receiver_id=admin.id, content='oi', lida=False)
        )
        db.session.commit()
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)

        assert inject_unread_count() == dict(unread_messages=0)


def test_mensagem_de_tutor_continua_acendendo_o_badge(monkeypatch, app):
    with app.app_context():
        admin, _, tutor = _make_users()
        db.session.add(
            Message(sender_id=tutor.id, receiver_id=admin.id, content='ajuda', lida=False)
        )
        db.session.commit()
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)

        assert inject_unread_count() == dict(unread_messages=1)


def test_badge_do_admin_cobre_o_pool_inteiro_sem_diferenciar_caixa(monkeypatch, app):
    """role='Admin' e role='admin' sao o mesmo pool no badge e na listagem."""
    with app.app_context():
        admin, outro_admin, tutor = _make_users()
        db.session.add(
            Message(sender_id=tutor.id, receiver_id=outro_admin.id, content='ajuda', lida=False)
        )
        db.session.commit()
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)

        assert inject_unread_count() == dict(unread_messages=1)


def test_badge_do_admin_bate_com_os_contadores_da_listagem(monkeypatch, app):
    """O total do badge nunca pode passar da soma exibida em /mensagens_admin."""
    from services.messages import admin_unread_count, admin_unread_counts_by_sender

    with app.app_context():
        admin, outro_admin, tutor = _make_users()
        db.session.add_all([
            Message(sender_id=outro_admin.id, receiver_id=admin.id, content='interno', lida=False),
            Message(sender_id=admin.id, receiver_id=admin.id, content='nota propria', lida=False),
            Message(sender_id=tutor.id, receiver_id=admin.id, content='ajuda', lida=False),
        ])
        db.session.commit()
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)

        assert admin_unread_count() == sum(admin_unread_counts_by_sender().values())
        assert admin_unread_counts_by_sender() == {tutor.id: 1}


def test_badge_pessoal_ignora_mensagem_de_remetente_removido(monkeypatch, app):
    """_get_inbox_messages descarta remetente inexistente; o badge tambem."""
    with app.app_context():
        _, _, tutor = _make_users()
        db.session.add(
            Message(sender_id=999, receiver_id=tutor.id, content='orfa', lida=False)
        )
        db.session.commit()
        monkeypatch.setattr(login_utils, '_get_user', lambda: tutor)

        assert inject_unread_count() == dict(unread_messages=0)
