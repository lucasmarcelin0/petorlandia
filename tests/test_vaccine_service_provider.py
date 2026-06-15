from decimal import Decimal

from extensions import db
from models import (
    Animal,
    Clinica,
    User,
    VaccineServiceItem,
    Veterinario,
)
from services.vaccine_service_paid import (
    complete_request,
    create_vaccine_request,
    mark_request_paid,
)


def test_paid_vaccine_keeps_provider_and_payout_snapshot(app):
    with app.app_context():
        tutor = User(name="Tutor", email="tutor-vaccine@example.com")
        tutor.set_password("x")
        provider_user = User(name="Maisse", email="maisse-vaccine@example.com")
        provider_user.set_password("x")
        db.session.add_all([tutor, provider_user])
        db.session.flush()

        clinic = Clinica(nome="Clínica Maisse", owner_id=provider_user.id)
        db.session.add(clinic)
        db.session.flush()
        vet = Veterinario(
            user_id=provider_user.id,
            clinica_id=clinic.id,
            crmv="12345",
        )
        animal = Animal(name="Bento", user_id=tutor.id)
        db.session.add_all([vet, animal])
        db.session.flush()

        item = VaccineServiceItem(
            nome="V10",
            fabricante="Zoetis",
            especies="cao",
            preco=Decimal("90.00"),
            valor_repasse=Decimal("80.00"),
            provider_vet_id=vet.id,
        )
        db.session.add(item)
        db.session.commit()

        req, payment_url = create_vaccine_request(
            user=tutor,
            animal=animal,
            item=item,
            payload={
                "phone": "(34) 99999-9999",
                "address_street": "Rua Teste",
            },
            criar_preferencia=lambda items, extref, back_url: {
                "payment_url": "https://payments.example/checkout",
            },
            back_url_builder=lambda token: f"https://example.test/pedido/{token}",
        )

        assert payment_url == "https://payments.example/checkout"
        assert req.assigned_vet_id == vet.id
        assert req.fabricante == "Zoetis"
        assert req.valor == Decimal("90.00")
        assert req.valor_repasse == Decimal("80.00")
        assert req.status == "pendente_pagamento"

        assert mark_request_paid(req) is True
        db.session.commit()
        assert req.status == "atribuido"
        assert [event.event for event in req.events][-2:] == ["pago", "atribuido"]


def test_vaccine_catalog_shows_clinic_product_and_pet_images(app, client):
    with app.app_context():
        tutor = User(name="Tutor", email="catalog-vaccine@example.com")
        tutor.set_password("x")
        provider_user = User(name="Maisse", email="catalog-maisse@example.com")
        provider_user.set_password("x")
        db.session.add_all([tutor, provider_user])
        db.session.flush()

        clinic = Clinica(
            nome="Clínica Maisse",
            owner_id=provider_user.id,
            logotipo="https://assets.example/clinic-logo.jpg",
        )
        db.session.add(clinic)
        db.session.flush()
        vet = Veterinario(
            user_id=provider_user.id,
            clinica_id=clinic.id,
            crmv="12345",
        )
        animal = Animal(
            name="Bento",
            user_id=tutor.id,
            image="https://assets.example/bento.jpg",
        )
        item = VaccineServiceItem(
            nome="V10",
            fabricante="Zoetis",
            descricao="Vacina múltipla canina.",
            image_url="uploads/vaccine_service/v10-zoetis-vanguard-plus.jpg",
            especies="cao",
            preco=Decimal("90.00"),
            valor_repasse=Decimal("80.00"),
            provider_vet=vet,
        )
        db.session.add_all([vet, animal, item])
        db.session.commit()
        tutor_id = tutor.id

    with client.session_transaction() as session:
        session["_user_id"] = str(tutor_id)
        session["_fresh"] = True

    response = client.get("/servicos/vacinas")

    assert response.status_code == 200
    assert b"https://assets.example/clinic-logo.jpg" in response.data
    assert b"uploads/vaccine_service/v10-zoetis-vanguard-plus.jpg" in response.data
    assert b"https://assets.example/bento.jpg" in response.data
    assert b'type="checkbox"' in response.data
    assert b'name="item_ids"' in response.data
    assert b"vacserv-selected-total" in response.data


def test_multiple_vaccines_share_checkout_and_create_separate_records(app):
    checkout = {}

    with app.app_context():
        tutor = User(name="Tutor", email="multi-vaccine@example.com")
        tutor.set_password("x")
        provider_user = User(name="Maisse", email="multi-maisse@example.com")
        provider_user.set_password("x")
        db.session.add_all([tutor, provider_user])
        db.session.flush()

        clinic = Clinica(nome="Clínica Maisse", owner_id=provider_user.id)
        db.session.add(clinic)
        db.session.flush()
        vet = Veterinario(user_id=provider_user.id, clinica_id=clinic.id, crmv="12345")
        animal = Animal(name="Bento", user_id=tutor.id)
        db.session.add_all([vet, animal])
        db.session.flush()

        v8 = VaccineServiceItem(
            nome="V8",
            fabricante="MSD",
            especies="cao",
            preco=Decimal("70.00"),
            valor_repasse=Decimal("60.00"),
            provider_vet_id=vet.id,
        )
        raiva = VaccineServiceItem(
            nome="Raiva",
            fabricante="Virbac",
            especies="cao",
            preco=Decimal("35.00"),
            valor_repasse=Decimal("30.00"),
            provider_vet_id=vet.id,
        )
        db.session.add_all([v8, raiva])
        db.session.commit()

        def create_preference(items, external_reference, back_url):
            checkout["items"] = items
            checkout["external_reference"] = external_reference
            checkout["back_url"] = back_url
            return {"payment_url": "https://payments.example/multiple"}

        req, payment_url = create_vaccine_request(
            user=tutor,
            animal=animal,
            items=[v8, raiva],
            payload={"phone": "34999999999", "address_street": "Rua Teste"},
            criar_preferencia=create_preference,
            back_url_builder=lambda token: f"https://example.test/{token}",
        )

        assert payment_url == "https://payments.example/multiple"
        assert [entry["title"] for entry in checkout["items"]] == [
            "V8 — Bento",
            "Raiva — Bento",
        ]
        assert req.valor == Decimal("105.00")
        assert req.valor_repasse == Decimal("90.00")
        assert req.payment.amount == Decimal("105.00")
        assert [entry.nome for entry in req.request_items] == ["V8", "Raiva"]

        req.status = "atribuido"
        complete_request(req, provider_user.id, lote="LOTE-1")
        db.session.commit()

        assert req.status == "concluido"
        assert [entry.vacina.nome for entry in req.request_items] == ["V8", "Raiva"]
        assert all(entry.vacina.lote == "LOTE-1" for entry in req.request_items)
