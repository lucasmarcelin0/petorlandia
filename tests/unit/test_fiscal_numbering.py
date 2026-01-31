import pytest

from extensions import db
from models import FiscalDocumentType, FiscalEmitter
from services.fiscal.numbering import reserve_next_number


def test_reserve_next_number_concurrent(app):
    with app.app_context():
        emitter = FiscalEmitter(
            clinic_id=1,
            cnpj="12.345.678/0001-90",
            razao_social="Clinica Teste",
        )
        db.session.add(emitter)
        db.session.commit()
        first = reserve_next_number(emitter.id, FiscalDocumentType.NFSE, "1")
        second = reserve_next_number(emitter.id, FiscalDocumentType.NFSE, "1")

    assert [first, second] == [1, 2]
