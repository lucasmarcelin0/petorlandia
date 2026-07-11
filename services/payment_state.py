"""Monotonic payment-state transitions shared by webhooks and return URLs."""

from __future__ import annotations

from models.loja import PaymentStatus


def advance_payment_status(
    current: PaymentStatus | None,
    incoming: PaymentStatus,
    *,
    provider_status: str | None = None,
) -> PaymentStatus:
    """Apply provider state without allowing stale webhook regressions."""
    if current == PaymentStatus.COMPLETED:
        if provider_status in {"refunded", "cancelled", "charged_back"}:
            return PaymentStatus.FAILED
        return current
    return incoming
