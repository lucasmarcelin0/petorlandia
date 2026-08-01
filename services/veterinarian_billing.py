"""Reliable Mercado Pago billing for veterinarian memberships."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import requests
from dateutil.parser import isoparse

from extensions import db
from models import (
    VeterinarianMembership,
    VeterinarianMembershipCharge,
    VeterinarianMembershipSubscription,
)
from time_utils import utcnow


_MEMBERSHIP_REFERENCE_RE = re.compile(r"^vet-membership-(\d+)(?:-|$)")
_CANCELED_STATUSES = {"canceled", "cancelled"}
_FAILED_PAYMENT_STATUSES = {
    "cancelled",
    "canceled",
    "charged_back",
    "refunded",
    "rejected",
}


class MercadoPagoBillingError(RuntimeError):
    """Raised when the provider cannot return authoritative billing data."""


class MercadoPagoSubscriptionClient:
    def __init__(self, access_token: str, timeout: float = 8.0):
        token = (access_token or "").strip()
        if not token:
            raise MercadoPagoBillingError("MERCADOPAGO_ACCESS_TOKEN ausente")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    def _get(self, path: str, *, params: dict | None = None) -> dict:
        try:
            response = requests.get(
                f"https://api.mercadopago.com{path}",
                headers=self._headers,
                params=params,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise MercadoPagoBillingError("falha de conexão com Mercado Pago") from exc
        if response.status_code == 404:
            raise LookupError(path)
        if not 200 <= response.status_code < 300:
            message = ""
            try:
                message = str((response.json() or {}).get("message") or "")
            except ValueError:
                pass
            raise MercadoPagoBillingError(
                f"Mercado Pago HTTP {response.status_code}: {message[:200]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MercadoPagoBillingError("resposta inválida do Mercado Pago") from exc
        if not isinstance(payload, dict):
            raise MercadoPagoBillingError("resposta inesperada do Mercado Pago")
        return payload

    def get_preapproval(self, preapproval_id: str) -> dict:
        return self._get(f"/preapproval/{preapproval_id}")

    def get_authorized_payment(self, invoice_id: str) -> dict:
        return self._get(f"/authorized_payments/{invoice_id}")

    def search_authorized_payments(self, preapproval_id: str) -> list[dict]:
        results = []
        page_size = 100
        for offset in range(0, 1000, page_size):
            payload = self._get(
                "/authorized_payments/search",
                params={
                    "preapproval_id": preapproval_id,
                    "limit": page_size,
                    "offset": offset,
                },
            )
            page = [
                item
                for item in (payload.get("results") or [])
                if isinstance(item, dict)
            ]
            results.extend(page)
            total = int((payload.get("paging") or {}).get("total") or 0)
            if len(page) < page_size or (total and len(results) >= total):
                break
        return results


def membership_id_from_reference(value: object) -> int | None:
    match = _MEMBERSHIP_REFERENCE_RE.match(str(value or ""))
    return int(match.group(1)) if match else None


def membership_plan_from_reference(value: object) -> str:
    parts = str(value or "").lower().split("-")
    return "anual" if "anual" in parts else "mensal"


def membership_plan_from_preapproval_payload(payload: dict) -> str:
    reference_plan = membership_plan_from_reference(
        payload.get("external_reference")
    )
    recurring = payload.get("auto_recurring") or {}
    try:
        frequency = int(recurring.get("frequency") or 1)
    except (TypeError, ValueError):
        frequency = 1
    frequency_type = str(recurring.get("frequency_type") or "").lower()
    if reference_plan == "anual" or (
        frequency_type == "months" and frequency >= 12
    ):
        return "anual"
    return "mensal"


def membership_cycle_days(value: object) -> int:
    return 365 if membership_plan_from_reference(value) == "anual" else 30


def normalize_preapproval_status(value: object) -> str:
    status = str(value or "unknown").strip().lower()
    return "canceled" if status in _CANCELED_STATUSES else status


def _decimal(value: object, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _provider_datetime(value: object):
    if not value:
        return None
    try:
        return isoparse(str(value))
    except (TypeError, ValueError):
        return None


def provider_response_payload(response: object) -> dict:
    if not isinstance(response, dict):
        return {}
    nested = response.get("response")
    return nested if isinstance(nested, dict) else response


def create_subscription_attempt(*, membership, plan_code: str, amount) -> object:
    token = uuid.uuid4().hex[:16]
    external_reference = f"vet-membership-{membership.id}-{token}-{plan_code}"
    attempt = VeterinarianMembershipSubscription(
        membership_id=membership.id,
        external_reference=external_reference,
        plan_code=plan_code,
        amount=_decimal(amount),
        currency="BRL",
        status="creating",
    )
    db.session.add(attempt)
    return attempt


def attach_created_preapproval(attempt, payload: dict) -> None:
    provider_id = str(payload.get("id") or "").strip()
    if not provider_id:
        raise MercadoPagoBillingError("Mercado Pago não retornou o ID da assinatura")
    attempt.provider_preapproval_id = provider_id[:64]
    attempt.init_point = payload.get("init_point") or payload.get("sandbox_init_point")
    attempt.provider_status = normalize_preapproval_status(payload.get("status") or "pending")
    attempt.status = attempt.provider_status
    attempt.last_error = None
    attempt.last_synced_at = utcnow()
    membership = attempt.membership
    membership.preapproval_id = attempt.provider_preapproval_id
    membership.payment_method_set_at = None
    db.session.add_all([attempt, membership])


def mark_subscription_attempt_failed(attempt, error: object) -> None:
    attempt.status = "failed"
    attempt.last_error = str(error or "erro desconhecido")[:500]
    attempt.last_synced_at = utcnow()
    db.session.add(attempt)


def _subscription_from_payload(payload: dict):
    provider_id = str(payload.get("id") or "").strip()
    external_reference = str(payload.get("external_reference") or "").strip()
    subscription = None
    if provider_id:
        subscription = VeterinarianMembershipSubscription.query.filter_by(
            provider_preapproval_id=provider_id
        ).first()
    if not subscription and external_reference:
        subscription = VeterinarianMembershipSubscription.query.filter_by(
            external_reference=external_reference
        ).first()
    return subscription, provider_id, external_reference


def sync_preapproval_payload(payload: dict):
    subscription, provider_id, external_reference = _subscription_from_payload(payload)
    membership = subscription.membership if subscription else None
    if not membership:
        membership_id = membership_id_from_reference(external_reference)
        if membership_id:
            membership = db.session.get(VeterinarianMembership, membership_id)
    if not membership and provider_id:
        membership = VeterinarianMembership.query.filter_by(
            preapproval_id=provider_id
        ).first()
    if not membership:
        return None

    auto_recurring = payload.get("auto_recurring") or {}
    plan_code = membership_plan_from_preapproval_payload(payload)
    if not subscription:
        external_reference = external_reference or (
            f"vet-membership-{membership.id}-legacy-"
            f"{plan_code}"
        )
        subscription = VeterinarianMembershipSubscription(
            membership_id=membership.id,
            provider_preapproval_id=provider_id[:64] if provider_id else None,
            external_reference=external_reference,
            plan_code=plan_code,
            amount=_decimal(auto_recurring.get("transaction_amount")),
            currency=str(auto_recurring.get("currency_id") or "BRL")[:3],
            status="pending",
        )
        db.session.add(subscription)

    status = normalize_preapproval_status(payload.get("status"))
    subscription.provider_status = status
    subscription.status = status
    subscription.init_point = (
        payload.get("init_point")
        or payload.get("sandbox_init_point")
        or subscription.init_point
    )
    subscription.last_synced_at = utcnow()
    subscription.last_error = None

    if status == "authorized":
        subscription.authorized_at = subscription.authorized_at or utcnow()
        if not subscription.superseded_at:
            membership.preapproval_id = provider_id[:64]
            membership.payment_method_set_at = (
                membership.payment_method_set_at or utcnow()
            )
    elif status == "canceled":
        if membership.preapproval_id == provider_id:
            membership.preapproval_id = None
            membership.payment_method_set_at = None
    elif status == "pending" and not subscription.superseded_at:
        if membership.preapproval_id in {None, provider_id}:
            membership.preapproval_id = provider_id[:64]

    db.session.add_all([subscription, membership])
    return subscription


def mark_subscription_superseded(subscription) -> None:
    subscription.superseded_at = subscription.superseded_at or utcnow()
    subscription.status = "superseded"
    db.session.add(subscription)


def current_subscription_for_membership(membership):
    if not membership or not membership.preapproval_id:
        return None
    return VeterinarianMembershipSubscription.query.filter_by(
        provider_preapproval_id=membership.preapproval_id
    ).first()


def _charge_subscription(external_reference: str, preapproval_id: object = None):
    subscription = None
    provider_id = str(preapproval_id or "").strip()
    if provider_id:
        subscription = VeterinarianMembershipSubscription.query.filter_by(
            provider_preapproval_id=provider_id
        ).first()
    if not subscription and external_reference:
        subscription = VeterinarianMembershipSubscription.query.filter_by(
            external_reference=external_reference
        ).first()
    return subscription


def sync_membership_payment_payload(payload: dict, *, invoice_id: object = None):
    provider_payment_id = str(payload.get("id") or "").strip()
    external_reference = str(payload.get("external_reference") or "").strip()
    if not provider_payment_id:
        return None

    subscription = _charge_subscription(
        external_reference,
        payload.get("preapproval_id") or payload.get("subscription_id"),
    )
    membership = subscription.membership if subscription else None
    if not membership:
        membership_id = membership_id_from_reference(external_reference)
        if membership_id:
            membership = db.session.get(VeterinarianMembership, membership_id)
    if not membership:
        provider_id = str(
            payload.get("preapproval_id") or payload.get("subscription_id") or ""
        ).strip()
        if provider_id:
            membership = VeterinarianMembership.query.filter_by(
                preapproval_id=provider_id
            ).first()
    if not membership:
        return None

    charge = VeterinarianMembershipCharge.query.filter_by(
        provider_payment_id=provider_payment_id
    ).first()
    cycle_reference = external_reference or (
        subscription.external_reference if subscription else ""
    )
    if not charge:
        charge = VeterinarianMembershipCharge(
            membership_id=membership.id,
            subscription_id=subscription.id if subscription else None,
            provider_payment_id=provider_payment_id[:64],
            external_reference=cycle_reference or None,
            status="pending",
            cycle_days=membership_cycle_days(cycle_reference),
        )
        db.session.add(charge)

    provider_status = str(payload.get("status") or "pending").strip().lower()
    charge.status = provider_status
    charge.provider_invoice_id = str(invoice_id)[:64] if invoice_id else charge.provider_invoice_id
    charge.external_reference = external_reference or charge.external_reference
    amount = payload.get("transaction_amount") or payload.get("amount")
    if amount is not None:
        charge.amount = _decimal(amount)
    if payload.get("currency_id"):
        charge.currency = str(payload["currency_id"])[:3]
    charge.provider_created_at = (
        _provider_datetime(payload.get("date_created")) or charge.provider_created_at
    )
    charge.paid_at = (
        _provider_datetime(payload.get("date_approved"))
        or _provider_datetime(payload.get("money_release_date"))
        or charge.paid_at
    )

    if provider_status in {"approved", "authorized"} and not charge.access_applied_at:
        now = utcnow()
        paid_until = VeterinarianMembership._as_timezone_aware(membership.paid_until)
        starts_at = paid_until if paid_until and paid_until > now else now
        membership.paid_until = starts_at + timedelta(days=charge.cycle_days)
        membership.ensure_trial_dates()
        charge.access_applied_at = now
        charge.paid_at = charge.paid_at or now
    elif provider_status in _FAILED_PAYMENT_STATUSES:
        charge.last_error = str(payload.get("status_detail") or provider_status)[:500]

    db.session.add_all([charge, membership])
    return charge


def sync_authorized_payment_payload(payload: dict):
    payment = payload.get("payment") or {}
    if isinstance(payment, dict):
        payment_id = payment.get("id")
        payment_status = payment.get("status")
        payment_status_detail = payment.get("status_detail")
    else:
        payment_id = payment
        payment_status = None
        payment_status_detail = None
    if not payment_id:
        return None
    payment_payload = {
        "id": payment_id,
        "status": payment_status or payload.get("summarized") or "pending",
        "status_detail": payment_status_detail,
        "external_reference": payload.get("external_reference"),
        "preapproval_id": payload.get("preapproval_id"),
        "transaction_amount": payload.get("transaction_amount"),
        "currency_id": payload.get("currency_id"),
        "date_created": payload.get("date_created"),
        "date_approved": payload.get("debit_date"),
    }
    return sync_membership_payment_payload(
        payment_payload,
        invoice_id=payload.get("id"),
    )


def reconcile_membership_billing(client, *, limit: int = 250) -> dict:
    max_records = max(1, int(limit))
    linked_provider_ids = (
        db.session.query(
            VeterinarianMembershipSubscription.provider_preapproval_id
        )
        .filter(
            VeterinarianMembershipSubscription.provider_preapproval_id.isnot(None)
        )
    )
    legacy_memberships = (
        VeterinarianMembership.query
        .filter(VeterinarianMembership.preapproval_id.isnot(None))
        .filter(VeterinarianMembership.preapproval_id.notin_(linked_provider_ids))
        .order_by(VeterinarianMembership.id.asc())
        .limit(max_records)
        .all()
    )
    legacy_provider_ids = {
        membership.preapproval_id for membership in legacy_memberships
    }

    remaining = max_records - len(legacy_memberships)
    subscriptions_query = (
        VeterinarianMembershipSubscription.query
        .filter(VeterinarianMembershipSubscription.provider_preapproval_id.isnot(None))
        .filter(
            VeterinarianMembershipSubscription.status.in_(
                ("creating", "pending", "authorized", "paused", "unknown")
            )
        )
        .order_by(VeterinarianMembershipSubscription.updated_at.asc())
    )
    if legacy_provider_ids:
        subscriptions_query = subscriptions_query.filter(
            VeterinarianMembershipSubscription.provider_preapproval_id.notin_(
                legacy_provider_ids
            )
        )
    subscriptions = subscriptions_query.limit(remaining).all() if remaining else []
    result = {
        "checked": 0,
        "subscriptions_updated": 0,
        "charges_seen": 0,
        "failures": 0,
        "missing": 0,
    }
    for membership in legacy_memberships:
        result["checked"] += 1
        provider_id = membership.preapproval_id
        try:
            payload = client.get_preapproval(provider_id)
            synced = sync_preapproval_payload(payload)
            if synced:
                result["subscriptions_updated"] += 1
            for invoice in client.search_authorized_payments(provider_id):
                if sync_authorized_payment_payload(invoice):
                    result["charges_seen"] += 1
            db.session.commit()
        except LookupError:
            db.session.rollback()
            current = db.session.get(VeterinarianMembership, membership.id)
            if current and current.preapproval_id == provider_id:
                current.preapproval_id = None
                current.payment_method_set_at = None
                db.session.add(current)
                db.session.commit()
            result["missing"] += 1
        except Exception:  # noqa: BLE001 - retry legacy records next run
            db.session.rollback()
            result["failures"] += 1

    for subscription in subscriptions:
        result["checked"] += 1
        provider_id = subscription.provider_preapproval_id
        try:
            payload = client.get_preapproval(provider_id)
            synced = sync_preapproval_payload(payload)
            if synced:
                result["subscriptions_updated"] += 1
            for invoice in client.search_authorized_payments(provider_id):
                if sync_authorized_payment_payload(invoice):
                    result["charges_seen"] += 1
            db.session.commit()
        except LookupError:
            db.session.rollback()
            current = db.session.get(
                VeterinarianMembershipSubscription, subscription.id
            )
            if current:
                current.status = "missing"
                current.provider_status = "missing"
                current.last_synced_at = utcnow()
                if current.membership.preapproval_id == provider_id:
                    current.membership.preapproval_id = None
                    current.membership.payment_method_set_at = None
                db.session.add(current)
                db.session.commit()
            result["missing"] += 1
        except Exception as exc:  # noqa: BLE001 - isolate provider records
            db.session.rollback()
            current = db.session.get(
                VeterinarianMembershipSubscription, subscription.id
            )
            if current:
                current.last_error = str(exc)[:500]
                current.last_synced_at = utcnow()
                db.session.add(current)
                db.session.commit()
            result["failures"] += 1
    return result
