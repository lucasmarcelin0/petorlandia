from types import SimpleNamespace
from datetime import datetime, timezone

from services import payments
from services.payments import (
    PaymentItemDTO,
    PaymentPreferenceDTO,
    PaymentPreferenceResult,
    apply_payment_to_bloco,
    apply_payment_to_orcamento,
    create_payment_preference,
)


class FakeSession:
    def __init__(self):
        self.flush_called = 0
        self.commit_called = 0
        self.added = []

    def flush(self):
        self.flush_called += 1

    def commit(self):
        self.commit_called += 1

    def add(self, item):
        self.added.append(item)


def test_create_payment_preference_builds_payload():
    items = [
        PaymentItemDTO(item_id="1", title="Consulta", quantity=1, unit_price=100.0),
        PaymentItemDTO(item_id="2", title="Vacina", quantity=2, unit_price=25.0),
    ]
    dto = PaymentPreferenceDTO(
        items=items,
        external_reference="ref-123",
        back_url="https://example.com/voltar",
    )
    received = {}

    def fake_create_preference(items_payload, external_reference, back_url):
        received["items_payload"] = items_payload
        received["external_reference"] = external_reference
        received["back_url"] = back_url
        return {
            "payment_url": "https://pay.example/abc",
            "payment_reference": "pref-001",
        }

    result = create_payment_preference(dto, fake_create_preference)

    assert received["items_payload"] == [
        {"id": "1", "title": "Consulta", "quantity": 1, "unit_price": 100.0},
        {"id": "2", "title": "Vacina", "quantity": 2, "unit_price": 25.0},
    ]
    assert received["external_reference"] == "ref-123"
    assert received["back_url"] == "https://example.com/voltar"
    assert result == PaymentPreferenceResult(
        payment_url="https://pay.example/abc",
        payment_reference="pref-001",
        payment_status="pending",
    )


def test_apply_payment_to_bloco_updates_and_commits(monkeypatch):
    bloco = SimpleNamespace(
        payment_link=None,
        payment_reference=None,
        payment_status=None,
    )
    preference = PaymentPreferenceResult(
        payment_url="https://pay.example/bloco",
        payment_reference="ref-bloco",
    )
    session = FakeSession()
    monkeypatch.setattr(payments.db, "session", session)

    synced = []

    def sync_payment_classification(target):
        synced.append(target)

    apply_payment_to_bloco(
        bloco=bloco,
        preference=preference,
        sync_payment_classification=sync_payment_classification,
    )

    assert bloco.payment_link == "https://pay.example/bloco"
    assert bloco.payment_reference == "ref-bloco"
    assert bloco.payment_status == "pending"
    assert session.flush_called == 1
    assert session.commit_called == 1
    assert synced == [bloco]


def test_apply_payment_to_orcamento_updates_status_and_commits(monkeypatch):
    orcamento = SimpleNamespace(
        payment_link=None,
        payment_reference=None,
        payment_status=None,
        paid_at="2024-01-01",
        status="draft",
        updated_at=None,
    )
    preference = PaymentPreferenceResult(
        payment_url="https://pay.example/orcamento",
        payment_reference="ref-orcamento",
    )
    session = FakeSession()
    monkeypatch.setattr(payments.db, "session", session)
    fixed_now = datetime(2024, 1, 2, tzinfo=timezone.utc)
    monkeypatch.setattr(payments, "utcnow", lambda: fixed_now)

    synced = []

    def sync_payment_classification(target):
        synced.append(target)

    apply_payment_to_orcamento(
        orcamento=orcamento,
        preference=preference,
        sync_payment_classification=sync_payment_classification,
    )

    assert orcamento.payment_link == "https://pay.example/orcamento"
    assert orcamento.payment_reference == "ref-orcamento"
    assert orcamento.payment_status == "pending"
    assert orcamento.paid_at is None
    assert orcamento.status == "sent"
    assert orcamento.updated_at == fixed_now
    assert session.flush_called == 1
    assert session.commit_called == 1
    assert session.added == [orcamento]
    assert synced == [orcamento]
