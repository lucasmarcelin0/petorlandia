from datetime import timedelta

import app as app_module
import blueprints.loja as loja_module

from extensions import db
from models import (
    User,
    Veterinario,
    VeterinarianMembership,
    VeterinarianMembershipCharge,
    VeterinarianMembershipSubscription,
)
from services.veterinarian_billing import (
    MercadoPagoSubscriptionClient,
    reconcile_membership_billing,
    sync_membership_payment_payload,
    sync_preapproval_payload,
)
from time_utils import utcnow


def _membership(email="billing@example.com"):
    user = User(name="Dra. Billing", email=email)
    user.set_password("segredo123")
    vet = Veterinario(user=user, crmv="32100", crmv_estado="SP")
    db.session.add(vet)
    db.session.commit()
    return VeterinarianMembership.query.filter_by(veterinario_id=vet.id).one()


def _subscription(membership, *, provider_id="pre-1", plan="mensal"):
    subscription = VeterinarianMembershipSubscription(
        membership_id=membership.id,
        provider_preapproval_id=provider_id,
        external_reference=f"vet-membership-{membership.id}-attempt-{plan}",
        plan_code=plan,
        amount=600 if plan == "anual" else 60,
        currency="BRL",
        status="authorized",
        provider_status="authorized",
        authorized_at=utcnow(),
    )
    membership.preapproval_id = provider_id
    membership.payment_method_set_at = utcnow()
    db.session.add_all([subscription, membership])
    db.session.commit()
    return subscription


def test_busca_de_faturas_percorre_paginacao(monkeypatch):
    client = MercadoPagoSubscriptionClient("token-de-teste")
    offsets = []

    def fake_get(path, *, params=None):
        assert path == "/authorized_payments/search"
        offsets.append(params["offset"])
        if params["offset"] == 0:
            return {
                "paging": {"total": 101},
                "results": [{"id": index} for index in range(100)],
            }
        return {"paging": {"total": 101}, "results": [{"id": 100}]}

    monkeypatch.setattr(client, "_get", fake_get)

    assert len(client.search_authorized_payments("pre-paginado")) == 101
    assert offsets == [0, 100]


def test_pagamento_recorrente_aplica_acesso_uma_unica_vez(app):
    membership = _membership()
    subscription = _subscription(membership)
    payload = {
        "id": "pay-1",
        "status": "approved",
        "external_reference": subscription.external_reference,
        "preapproval_id": subscription.provider_preapproval_id,
        "transaction_amount": 60,
        "currency_id": "BRL",
        "date_approved": "2026-08-01T12:00:00Z",
    }

    first = sync_membership_payment_payload(payload)
    db.session.commit()
    first_paid_until = membership.paid_until
    assert first.access_applied_at is not None

    second = sync_membership_payment_payload(payload)
    db.session.commit()

    assert second.id == first.id
    assert membership.paid_until == first_paid_until
    assert VeterinarianMembershipCharge.query.count() == 1


def test_cada_nova_mensalidade_gera_cobranca_e_novo_periodo(app):
    membership = _membership("segunda@example.com")
    subscription = _subscription(membership, provider_id="pre-2")

    for payment_id in ("pay-a", "pay-b"):
        sync_membership_payment_payload(
            {
                "id": payment_id,
                "status": "approved",
                "external_reference": subscription.external_reference,
                "preapproval_id": subscription.provider_preapproval_id,
                "transaction_amount": 60,
                "currency_id": "BRL",
            }
        )
        db.session.commit()

    assert VeterinarianMembershipCharge.query.count() == 2
    paid_until = VeterinarianMembership._as_timezone_aware(membership.paid_until)
    assert paid_until >= utcnow() + timedelta(days=59)


def test_cobranca_anual_usa_plano_local_quando_referencia_nao_vem(app):
    membership = _membership("anual-sem-referencia@example.com")
    subscription = _subscription(
        membership,
        provider_id="pre-anual-sem-referencia",
        plan="anual",
    )

    charge = sync_membership_payment_payload(
        {
            "id": "pay-anual-sem-referencia",
            "status": "approved",
            "preapproval_id": subscription.provider_preapproval_id,
            "transaction_amount": 600,
            "currency_id": "BRL",
        }
    )
    db.session.commit()

    paid_until = VeterinarianMembership._as_timezone_aware(membership.paid_until)
    assert charge.cycle_days == 365
    assert paid_until >= utcnow() + timedelta(days=364)


def test_webhook_payment_da_assinatura_e_idempotente(app, client, monkeypatch):
    membership = _membership("webhook@example.com")
    subscription = _subscription(membership, provider_id="pre-webhook")
    payload = {
        "id": "998877",
        "status": "approved",
        "external_reference": subscription.external_reference,
        "preapproval_id": subscription.provider_preapproval_id,
        "transaction_amount": 60,
        "currency_id": "BRL",
    }

    class FakePayment:
        def get(self, payment_id):
            assert str(payment_id) == "998877"
            return {"status": 200, "response": payload}

    class FakeSDK:
        def payment(self):
            return FakePayment()

    monkeypatch.setattr(app_module, "verify_mp_signature", lambda req, secret: True)
    monkeypatch.setattr(app_module, "mp_sdk", lambda: FakeSDK())

    for _ in range(2):
        response = client.post(
            "/notificacoes?type=payment",
            json={"data": {"id": "998877"}},
        )
        assert response.status_code == 200

    assert VeterinarianMembershipCharge.query.count() == 1
    charge = VeterinarianMembershipCharge.query.one()
    assert charge.access_applied_at is not None


def test_preapproval_webhook_autoriza_pagamento_configurado(app):
    membership = _membership("preapproval@example.com")
    subscription = _subscription(
        membership, provider_id="pre-authorize", plan="anual"
    )
    membership.payment_method_set_at = None
    subscription.status = "pending"
    subscription.provider_status = "pending"
    db.session.commit()

    synced = sync_preapproval_payload(
        {
            "id": "pre-authorize",
            "status": "authorized",
            "external_reference": subscription.external_reference,
            "init_point": "https://mp.example/subscription",
            "auto_recurring": {
                "transaction_amount": 600,
                "currency_id": "BRL",
            },
        }
    )
    db.session.commit()

    assert synced.status == "authorized"
    assert membership.has_payment_method()


def test_webhook_preapproval_busca_estado_autoritativo(app, client, monkeypatch):
    membership = _membership("preapproval-route@example.com")
    subscription = _subscription(membership, provider_id="pre-route")
    membership.payment_method_set_at = None
    subscription.status = "pending"
    subscription.provider_status = "pending"
    db.session.commit()

    class FakeClient:
        def __init__(self, access_token):
            self.access_token = access_token

        def get_preapproval(self, preapproval_id):
            assert preapproval_id == "pre-route"
            return {
                "id": preapproval_id,
                "status": "authorized",
                "external_reference": subscription.external_reference,
                "auto_recurring": {
                    "transaction_amount": 60,
                    "currency_id": "BRL",
                },
            }

    monkeypatch.setattr(app_module, "verify_mp_signature", lambda req, secret: True)
    monkeypatch.setattr(loja_module, "MercadoPagoSubscriptionClient", FakeClient)

    response = client.post(
        "/notificacoes?type=subscription_preapproval",
        json={"data": {"id": "pre-route"}},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
    assert membership.has_payment_method()


def test_webhook_fatura_recorrente_aplica_acesso_uma_vez(app, client, monkeypatch):
    membership = _membership("invoice-route@example.com")
    subscription = _subscription(membership, provider_id="pre-invoice")

    class FakeClient:
        def __init__(self, access_token):
            self.access_token = access_token

        def get_authorized_payment(self, invoice_id):
            assert invoice_id == "invoice-route"
            return {
                "id": invoice_id,
                "preapproval_id": subscription.provider_preapproval_id,
                "external_reference": subscription.external_reference,
                "transaction_amount": 60,
                "currency_id": "BRL",
                "payment": {"id": "payment-route", "status": "approved"},
            }

    monkeypatch.setattr(app_module, "verify_mp_signature", lambda req, secret: True)
    monkeypatch.setattr(loja_module, "MercadoPagoSubscriptionClient", FakeClient)

    for _ in range(2):
        response = client.post(
            "/notificacoes?type=subscription_authorized_payment",
            json={"data": {"id": "invoice-route"}},
        )
        assert response.status_code == 200

    assert VeterinarianMembershipCharge.query.count() == 1
    assert VeterinarianMembershipCharge.query.one().access_applied_at is not None


def test_reconciliacao_recupera_webhook_perdido_sem_duplicar_acesso(app):
    membership = _membership("reconcile@example.com")
    subscription = _subscription(membership, provider_id="pre-reconcile")

    class FakeClient:
        def get_preapproval(self, preapproval_id):
            return {
                "id": preapproval_id,
                "status": "authorized",
                "external_reference": subscription.external_reference,
                "auto_recurring": {
                    "transaction_amount": 60,
                    "currency_id": "BRL",
                },
            }

        def search_authorized_payments(self, preapproval_id):
            return [
                {
                    "id": "invoice-1",
                    "preapproval_id": preapproval_id,
                    "external_reference": subscription.external_reference,
                    "transaction_amount": 60,
                    "currency_id": "BRL",
                    "payment": {"id": "pay-reconcile", "status": "approved"},
                }
            ]

    first = reconcile_membership_billing(FakeClient())
    paid_until = membership.paid_until
    second = reconcile_membership_billing(FakeClient())

    assert first["charges_seen"] == 1
    assert second["charges_seen"] == 1
    assert membership.paid_until == paid_until
    assert VeterinarianMembershipCharge.query.count() == 1


def test_reconciliacao_importa_assinatura_legada_e_suas_cobrancas(app):
    membership = _membership("legacy-reconcile@example.com")
    membership.preapproval_id = "pre-legacy"
    db.session.commit()

    class FakeClient:
        def get_preapproval(self, preapproval_id):
            assert preapproval_id == "pre-legacy"
            return {
                "id": preapproval_id,
                "status": "authorized",
                "auto_recurring": {
                    "frequency": 12,
                    "frequency_type": "months",
                    "transaction_amount": 600,
                    "currency_id": "BRL",
                },
            }

        def search_authorized_payments(self, preapproval_id):
            return [
                {
                    "id": "invoice-legacy",
                    "preapproval_id": preapproval_id,
                    "transaction_amount": 600,
                    "currency_id": "BRL",
                    "payment": {"id": "pay-legacy", "status": "approved"},
                }
            ]

    result = reconcile_membership_billing(FakeClient())

    assert result == {
        "checked": 1,
        "subscriptions_updated": 1,
        "charges_seen": 1,
        "failures": 0,
        "missing": 0,
    }
    subscription = VeterinarianMembershipSubscription.query.one()
    charge = VeterinarianMembershipCharge.query.one()
    assert subscription.plan_code == "anual"
    assert subscription.external_reference.endswith("-legacy-anual")
    assert charge.subscription_id == subscription.id
    assert charge.cycle_days == 365
    assert charge.access_applied_at is not None


def test_reconciliacao_limpa_preapproval_legado_que_nao_existe_mais(app):
    membership = _membership("legacy-missing@example.com")
    membership.preapproval_id = "pre-missing"
    db.session.commit()

    class FakeClient:
        def get_preapproval(self, preapproval_id):
            raise LookupError(preapproval_id)

        def search_authorized_payments(self, preapproval_id):
            raise AssertionError("não deve buscar cobranças de assinatura ausente")

    result = reconcile_membership_billing(FakeClient())

    assert result["checked"] == 1
    assert result["missing"] == 1
    assert membership.preapproval_id is None


def test_reconciliacao_nao_busca_fatura_para_assinatura_legada_pendente(app):
    membership = _membership("legacy-pending@example.com")
    membership.preapproval_id = "pre-pending-legacy"
    db.session.commit()

    class FakeClient:
        def get_preapproval(self, preapproval_id):
            return {
                "id": preapproval_id,
                "status": "pending",
                "external_reference": f"vet-membership-{membership.id}",
                "auto_recurring": {
                    "frequency": 1,
                    "frequency_type": "months",
                    "transaction_amount": 60,
                    "currency_id": "BRL",
                },
            }

        def search_authorized_payments(self, preapproval_id):
            raise AssertionError("assinatura pendente ainda não possui faturas")

    result = reconcile_membership_billing(FakeClient())

    assert result["checked"] == 1
    assert result["subscriptions_updated"] == 1
    assert result["charges_seen"] == 0
    assert result["failures"] == 0
    assert VeterinarianMembershipSubscription.query.one().status == "pending"
