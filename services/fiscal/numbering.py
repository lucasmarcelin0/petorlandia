"""Serviço de numeração fiscal com controle de concorrência."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError, InvalidRequestError

from extensions import db
from models import FiscalCounter, FiscalDocumentType


def _normalize_doc_type(doc_type: FiscalDocumentType | str) -> FiscalDocumentType:
    if isinstance(doc_type, FiscalDocumentType):
        return doc_type
    try:
        return FiscalDocumentType[str(doc_type).upper()]
    except KeyError as exc:  # pragma: no cover - validação defensiva
        raise ValueError(f"Tipo de documento fiscal inválido: {doc_type}") from exc


def reserve_next_number(emitter_id: int, doc_type: FiscalDocumentType | str, series: str) -> int:
    """Reserve o próximo número fiscal com lock por emissor/tipo/série."""
    normalized_type = _normalize_doc_type(doc_type)
    normalized_series = str(series or "1")
    session = db.session

    while True:
        try:
            try:
                transaction_ctx = session.begin()
            except InvalidRequestError:
                transaction_ctx = session.begin_nested()
            with transaction_ctx:
                counter = (
                    session.query(FiscalCounter)
                    .filter_by(
                        emitter_id=emitter_id,
                        doc_type=normalized_type,
                        series=normalized_series,
                    )
                    .with_for_update()
                    .first()
                )
                if counter is None:
                    counter = FiscalCounter(
                        emitter_id=emitter_id,
                        doc_type=normalized_type,
                        series=normalized_series,
                        current_number=1,
                    )
                    session.add(counter)
                    session.flush()
                    return counter.current_number
                counter.current_number += 1
                session.flush()
                return counter.current_number
        except IntegrityError:
            session.rollback()
