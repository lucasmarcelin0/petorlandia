from models.loja import PaymentStatus
from services.payment_state import advance_payment_status


def test_completed_payment_ignores_stale_pending_or_failure():
    assert advance_payment_status(PaymentStatus.COMPLETED, PaymentStatus.PENDING, provider_status='pending') == PaymentStatus.COMPLETED
    assert advance_payment_status(PaymentStatus.COMPLETED, PaymentStatus.FAILED, provider_status='rejected') == PaymentStatus.COMPLETED


def test_completed_payment_accepts_explicit_refund_or_cancel():
    assert advance_payment_status(PaymentStatus.COMPLETED, PaymentStatus.FAILED, provider_status='refunded') == PaymentStatus.FAILED


def test_pending_payment_can_advance():
    assert advance_payment_status(PaymentStatus.PENDING, PaymentStatus.COMPLETED, provider_status='approved') == PaymentStatus.COMPLETED
