"""Message data access helpers."""

from __future__ import annotations

from sqlalchemy.orm import selectinload

from extensions import db
from models import Message


class MessageRepository:
    """Encapsulate message queries."""

    def __init__(self, session=None) -> None:
        self._session = session or db.session

    def inbox_query(self, receiver_id: int):
        return (
            Message.query.options(
                selectinload(Message.sender),
                selectinload(Message.receiver),
                selectinload(Message.animal),
            )
            .filter(Message.receiver_id == receiver_id)
        )

    def paginate_inbox(self, *, receiver_id: int, page: int, per_page: int):
        return (
            self.inbox_query(receiver_id)
            .order_by(Message.timestamp.desc().nullslast())
            .paginate(page=page, per_page=per_page, error_out=False)
        )

    def list_conversation(
        self,
        *,
        animal_id: int,
        user_id: int,
        other_id: int,
        page: int,
        per_page: int,
    ):
        return (
            Message.query.options(
                selectinload(Message.sender),
                selectinload(Message.receiver),
            )
            .filter(
                Message.animal_id == animal_id,
                (
                    ((Message.sender_id == user_id) & (Message.receiver_id == other_id))
                    | ((Message.sender_id == other_id) & (Message.receiver_id == user_id))
                ),
            )
            .order_by(Message.timestamp.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )

    def list_admin_conversation(
        self,
        *,
        admin_ids: list[int],
        participant_id: int,
        page: int,
        per_page: int,
    ):
        return (
            Message.query.options(
                selectinload(Message.sender),
                selectinload(Message.receiver),
            )
            .filter(
                ((Message.sender_id.in_(admin_ids)) & (Message.receiver_id == participant_id))
                | ((Message.sender_id == participant_id) & (Message.receiver_id.in_(admin_ids)))
            )
            .order_by(Message.timestamp.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )

    def admin_threads_query(self, *, admin_ids: list[int], kind: str):
        query = (
            Message.query.options(
                selectinload(Message.sender),
                selectinload(Message.receiver),
                selectinload(Message.animal),
            )
            .filter(
                (Message.sender_id.in_(admin_ids))
                | (Message.receiver_id.in_(admin_ids))
            )
            .order_by(Message.timestamp.desc())
        )
        if kind == "animals":
            return query.filter(Message.animal_id.isnot(None))
        return query.filter(Message.animal_id.is_(None))

    def list_animal_messages(
        self,
        *,
        animal_id: int,
        page: int,
        per_page: int,
    ):
        return (
            Message.query.filter_by(animal_id=animal_id)
            .order_by(Message.timestamp.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
