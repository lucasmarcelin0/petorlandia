"""Payment-related service helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List

from extensions import db
from time_utils import utcnow


@dataclass(frozen=True)
class PaymentItemDTO:
    item_id: str
    title: str
    quantity: int
    unit_price: float

    def to_payload(self) -> dict:
        return {
            "id": str(self.item_id),
            "title": self.title,
            "quantity": int(self.quantity),
            "unit_price": float(self.unit_price),
        }


@dataclass(frozen=True)
class PaymentPreferenceDTO:
    items: List[PaymentItemDTO]
    external_reference: str
    back_url: str


@dataclass(frozen=True)
class PaymentPreferenceResult:
    payment_url: str
    payment_reference: str
    payment_status: str = "pending"


def create_payment_preference(
    dto: PaymentPreferenceDTO,
    create_preference: Callable[[Iterable[dict], str, str], dict],
) -> PaymentPreferenceResult:
    items_payload = [item.to_payload() for item in dto.items]
    preference_info = create_preference(
        items_payload, dto.external_reference, dto.back_url
    )
    return PaymentPreferenceResult(
        payment_url=preference_info["payment_url"],
        payment_reference=preference_info["payment_reference"],
    )


def apply_payment_to_bloco(
    *,
    bloco,
    preference: PaymentPreferenceResult,
    sync_payment_classification: Callable[[object], None],
) -> None:
    bloco.payment_link = preference.payment_url
    bloco.payment_reference = preference.payment_reference
    bloco.payment_status = preference.payment_status
    db.session.flush()
    sync_payment_classification(bloco)
    db.session.commit()


def apply_payment_to_orcamento(
    *,
    orcamento,
    preference: PaymentPreferenceResult,
    sync_payment_classification: Callable[[object], None],
) -> None:
    orcamento.payment_link = preference.payment_url
    orcamento.payment_reference = preference.payment_reference
    orcamento.payment_status = preference.payment_status
    orcamento.paid_at = None
    if orcamento.status == "draft":
        orcamento.status = "sent"
    orcamento.updated_at = utcnow()
    db.session.add(orcamento)
    db.session.flush()
    sync_payment_classification(orcamento)
    db.session.commit()
