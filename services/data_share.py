"""Helpers for auditing shared data accesses."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Sequence

from flask import has_request_context, request
from flask_login import current_user
from sqlalchemy import and_, or_

from extensions import db
from models import DataShareAccess, DataShareLog, DataSharePartyType


Party = tuple[DataSharePartyType, int]


def _now() -> datetime:
    return datetime.utcnow()


def _party_clauses(parties: Sequence[Party]):
    clauses = []
    for party_type, party_id in parties:
        if party_type is None or party_id is None:
            continue
        clauses.append(
            and_(
                DataShareAccess.granted_to_type == party_type,
                DataShareAccess.granted_to_id == party_id,
            )
        )
    return clauses


def find_active_share(
    parties: Iterable[Party], *, user_id: int | None = None, animal_id: int | None = None
) -> DataShareAccess | None:
    """Return the newest active share that grants access to the resource."""

    party_list = [p for p in parties if p and p[1] is not None]
    if not party_list:
        return None
    filters = []
    if user_id:
        filters.append(DataShareAccess.user_id == user_id)
    if animal_id:
        filters.append(DataShareAccess.animal_id == animal_id)
    if not filters:
        return None

    query = DataShareAccess.query.filter(or_(*filters))
    query = query.filter(DataShareAccess.revoked_at.is_(None))
    query = query.filter(
        or_(
            DataShareAccess.expires_at.is_(None),
            DataShareAccess.expires_at > _now(),
        )
    )
    clauses = _party_clauses(party_list)
    if not clauses:
        return None
    query = query.filter(or_(*clauses))
    return query.order_by(DataShareAccess.created_at.desc()).first()


def log_data_share_event(
    access: DataShareAccess,
    *,
    event_type: str,
    resource_type: str,
    resource_id: int | None = None,
    actor=None,
    notes: str | None = None,
) -> DataShareLog:
    """Persist an audit log describing how the shared data was used."""

    if not actor and current_user.is_authenticated:
        actor = current_user

    log = DataShareLog(
        access=access,
        actor_id=getattr(actor, 'id', None),
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        notes=notes,
        occurred_at=_now(),
    )
    if has_request_context():
        log.request_path = request.path
        log.request_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    db.session.add(log)
    return log
