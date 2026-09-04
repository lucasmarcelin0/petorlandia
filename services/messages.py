"""Contagem de mensagens não lidas — fonte única do badge da navbar.

O badge só pode contar mensagens que a caixa de entrada correspondente
consegue de fato mostrar. Quando as duas consultas divergem nasce a
"notificação fantasma": a navbar acusa mensagem nova, o usuário abre a
caixa e não encontra nada para ler.

Divergências que este módulo elimina:

* ``role`` do admin comparado ora com ``== 'admin'`` ora com ``lower()``:
  o pool de admins do badge precisa ser o mesmo pool da listagem.
* mensagens de admin para admin: ``mensagens_admin`` descarta toda mensagem
  cujo remetente é admin (``if message.sender_id in admin_ids: continue``),
  então elas nunca viram thread — contá-las deixa o badge preso para sempre.
* mensagens órfãs (remetente removido): ``_get_inbox_messages`` já as ignora
  na caixa pessoal, então o badge pessoal também precisa ignorá-las.
"""
from __future__ import annotations

from extensions import db


def admin_user_ids():
    """IDs do pool de admins, comparando o papel sem diferenciar caixa."""
    from models import User

    return [
        row[0]
        for row in db.session.query(User.id)
        .filter(db.func.lower(User.role) == 'admin')
        .all()
    ]


def admin_inbox_unread_query(admin_ids=None):
    """Não lidas endereçadas ao pool de admins que viram thread na listagem."""
    from models import Message

    if admin_ids is None:
        admin_ids = admin_user_ids()
    if not admin_ids:
        return Message.query.filter(db.false())

    return Message.query.filter(
        Message.receiver_id.in_(admin_ids),
        Message.lida.is_(False),
        Message.sender_id.notin_(admin_ids),
    )


def admin_unread_count(admin_ids=None):
    return admin_inbox_unread_query(admin_ids).count()


def admin_unread_counts_by_sender(admin_ids=None):
    """Mapa remetente -> não lidas, no mesmo escopo do badge."""
    from models import Message

    if admin_ids is None:
        admin_ids = admin_user_ids()
    if not admin_ids:
        return {}

    rows = (
        db.session.query(Message.sender_id, db.func.count())
        .filter(
            Message.receiver_id.in_(admin_ids),
            Message.lida.is_(False),
            Message.sender_id.notin_(admin_ids),
        )
        .group_by(Message.sender_id)
        .all()
    )
    return {sender_id: total for sender_id, total in rows}


def personal_unread_count(user_id):
    """Não lidas da caixa pessoal, ignorando remetentes que não existem mais."""
    from models import Message, User

    return (
        Message.query
        .filter(
            Message.receiver_id == user_id,
            Message.lida.is_(False),
            Message.sender_id.in_(db.session.query(User.id)),
        )
        .count()
    )
