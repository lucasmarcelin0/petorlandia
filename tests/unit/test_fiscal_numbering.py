from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from extensions import db
from models import FiscalDocumentType, FiscalEmitter
from services.fiscal.numbering import (
    NumberingReservationError,
    reserve_next_number,
)


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


def test_reserve_next_number_raises_after_max_retries(app):
    """Regressão: antes do fix, IntegrityError repetido travava em while True.
    Agora precisa levantar NumberingReservationError depois de 8 tentativas."""
    with app.app_context():
        emitter = FiscalEmitter(
            clinic_id=1,
            cnpj="12.345.678/0001-91",
            razao_social="Clinica Teste Retry",
        )
        db.session.add(emitter)
        db.session.commit()

        # Forçamos o flush a SEMPRE levantar IntegrityError — simula um
        # unique-constraint conflict permanente (bug no schema, por exemplo).
        # sleep é mockado pra teste rápido (sem 8×backoffs reais).
        fake_err = IntegrityError("stmt", {}, Exception("duplicate"))
        with patch(
            "services.fiscal.numbering.db.session.flush",
            side_effect=fake_err,
        ), patch("services.fiscal.numbering._sleep_with_backoff"):
            with pytest.raises(NumberingReservationError) as exc_info:
                reserve_next_number(emitter.id, FiscalDocumentType.NFSE, "1")

        msg = str(exc_info.value)
        assert "8 tentativas" in msg, msg
        assert "emitter_id" in msg
        # A exceção encadeada preserva o IntegrityError original para auditoria.
        assert isinstance(exc_info.value.__cause__, IntegrityError)


def test_reserve_next_number_retry_em_operational_error(app):
    """SQLite 'database is locked' vira OperationalError. Deve ser tratado
    como transiente e retry com backoff — e eventualmente ter sucesso."""
    with app.app_context():
        emitter = FiscalEmitter(
            clinic_id=1,
            cnpj="12.345.678/0001-92",
            razao_social="Clinica Teste OpErr",
        )
        db.session.add(emitter)
        db.session.commit()

        call_count = {"n": 0}
        real_flush = db.session.flush

        def flaky_flush(*args, **kwargs):
            # Falha nas 2 primeiras chamadas, depois funciona.
            call_count["n"] += 1
            if call_count["n"] <= 2:
                raise OperationalError("stmt", {}, Exception("database is locked"))
            return real_flush(*args, **kwargs)

        with patch(
            "services.fiscal.numbering.db.session.flush",
            side_effect=flaky_flush,
        ), patch("services.fiscal.numbering._sleep_with_backoff"):
            num = reserve_next_number(emitter.id, FiscalDocumentType.NFSE, "1")

        assert num == 1
        assert call_count["n"] >= 3  # 2 falhas + 1 sucesso


def test_reserve_next_number_backoff_cresce_exponencial():
    """Validação pura (sem DB) do cálculo de backoff: deve dobrar a cada
    retry, com jitter ±25%. Base = 5ms."""
    from services.fiscal.numbering import _INITIAL_BACKOFF_SECONDS, _sleep_with_backoff

    sleeps: list[float] = []
    with patch("services.fiscal.numbering.time.sleep", side_effect=sleeps.append):
        for attempt in range(4):
            _sleep_with_backoff(attempt)

    assert len(sleeps) == 4
    # Cada retry deve estar na faixa [base*(2^n)*0.75, base*(2^n)*1.25]
    for n, s in enumerate(sleeps):
        expected = _INITIAL_BACKOFF_SECONDS * (2 ** n)
        assert 0.75 * expected <= s <= 1.25 * expected, (
            f"attempt {n}: esperado ~{expected}s, recebi {s}s"
        )
