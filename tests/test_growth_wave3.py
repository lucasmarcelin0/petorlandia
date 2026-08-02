"""Code-only growth improvements from the third audit delivery."""

from datetime import date, timedelta
from decimal import Decimal

from extensions import db
from models import (
    Animal,
    Appointment,
    Clinica,
    Orcamento,
    OrcamentoItem,
    Product,
    User,
    Vacina,
    Veterinario,
    VeterinarianMembership,
)
from time_utils import utcnow


def _user(name, email, role="adotante", worker=None):
    user = User(
        name=name,
        email=email,
        password_hash="x",
        role=role,
        worker=worker,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


def test_pet_recommendations_are_explainable_and_do_not_prescribe(app):
    from services.pet_growth import build_pet_opportunities

    with app.test_request_context("/animal/1/ficha"):
        tutor = _user("Tutor", "growth3-tutor@example.test")
        animal = Animal(name="Nina", user_id=tutor.id, modo="pessoal")
        product = Product(
            name="Tapete higiênico",
            description="Uso doméstico",
            price=20,
            stock=4,
            status="active",
            is_demo=False,
        )
        db.session.add_all([animal, product])
        db.session.flush()
        db.session.add(Vacina(
            animal_id=animal.id,
            nome="Dose a confirmar",
            aplicada=False,
            aplicada_em=date.today() - timedelta(days=10),
        ))
        db.session.commit()

        opportunities = build_pet_opportunities(animal)

    assert [item["kind"] for item in opportunities] == ["vaccine", "checkup", "store"]
    combined = " ".join(item["description"] for item in opportunities).lower()
    assert "confirme" in combined
    assert "medicamento" not in combined
    assert all(item["event"].startswith("recommendation_") for item in opportunities)


def test_clinic_value_report_counts_recorded_value_and_retention(app):
    from services.clinic_value import build_clinic_value_report

    owner = _user("Owner", "growth3-owner@example.test", role="veterinario", worker="veterinario")
    tutor = _user("Tutor", "growth3-client@example.test")
    clinic = Clinica(nome="Clínica Métrica", owner_id=owner.id)
    vet = Veterinario(user_id=owner.id, crmv="12345")
    db.session.add_all([clinic, vet])
    db.session.flush()
    vet.clinica_id = clinic.id
    animal = Animal(name="Rex", user_id=tutor.id, clinica_id=clinic.id, modo="pessoal")
    db.session.add(animal)
    db.session.flush()
    now = utcnow()
    db.session.add_all([
        Appointment(
            animal_id=animal.id, tutor_id=tutor.id, veterinario_id=vet.id,
            clinica_id=clinic.id, scheduled_at=now - timedelta(days=4), status="completed",
        ),
        Appointment(
            animal_id=animal.id, tutor_id=tutor.id, veterinario_id=vet.id,
            clinica_id=clinic.id, scheduled_at=now - timedelta(days=70), status="completed",
        ),
    ])
    budget = Orcamento(
        clinica_id=clinic.id,
        descricao="Atendimento",
        status="approved",
        payment_status="paid",
        paid_at=now - timedelta(days=2),
        created_at=now - timedelta(days=3),
    )
    db.session.add(budget)
    db.session.flush()
    db.session.add(OrcamentoItem(
        orcamento_id=budget.id,
        clinica_id=clinic.id,
        descricao="Consulta",
        valor=Decimal("150.00"),
    ))
    db.session.commit()

    report = build_clinic_value_report(clinic.id, 30)

    assert report["appointments"]["total"] == 1
    assert report["appointments"]["completed"] == 1
    assert report["returning_patients"] == 1
    assert report["returning_rate"] == 100.0
    assert report["paid_value"] == Decimal("150.00")


def test_clinic_value_page_is_owner_only_and_explains_limits(app, client):
    owner = _user("Dona", "growth3-page-owner@example.test")
    clinic = Clinica(nome="Clínica Transparente", owner_id=owner.id)
    db.session.add(clinic)
    db.session.commit()

    _login(client, owner)
    response = client.get(f"/clinica/{clinic.id}/valor?periodo=90")
    body = response.data.decode()
    assert response.status_code == 200
    assert "Valor registrado" in body
    assert "não prova" in body
    assert "Em aberto, sem garantia de conversão" in body


def test_clinic_value_page_rejects_non_owner(app, client):
    owner = _user("Dona", "growth3-other-owner@example.test")
    stranger = _user("Outra", "growth3-stranger@example.test")
    clinic = Clinica(nome="Clínica Privada", owner_id=owner.id)
    db.session.add(clinic)
    db.session.commit()
    _login(client, stranger)

    assert client.get(f"/clinica/{clinic.id}/valor").status_code in (403, 404)


def test_public_health_card_has_growth_cta_without_contact_data(app, client):
    tutor = _user("Maria Souza", "growth3-card@example.test")
    tutor.phone = "11999999999"
    tutor.address = "Rua que não pode aparecer"
    animal = Animal(name="Luna", user_id=tutor.id, modo="pessoal", public_token="growth-card-token")
    db.session.add(animal)
    db.session.commit()

    response = client.get("/carteirinha/growth-card-token")
    body = response.data.decode()
    assert response.status_code == 200
    assert "Criar conta grátis" in body
    assert 'data-cta="health_card_signup"' in body
    assert tutor.phone not in body
    assert tutor.address not in body


def test_membership_describes_free_continuity_mode(app, client):
    vet_user = _user(
        "Veterinária", "growth3-vet@example.test", role="veterinario", worker="veterinario"
    )
    vet = Veterinario(user_id=vet_user.id, crmv="9999")
    db.session.add(vet)
    db.session.flush()
    membership = VeterinarianMembership.query.filter_by(veterinario_id=vet.id).one()
    membership.started_at = utcnow() - timedelta(days=60)
    membership.trial_ends_at = utcnow() - timedelta(days=30)
    db.session.commit()
    _login(client, vet_user)

    response = client.get("/veterinario/assinatura")
    body = response.data.decode()
    assert response.status_code == 200
    assert "Modo Continuidade gratuito" in body
    assert "R$ 0" in body
    assert "não há cobrança" in body


def test_product_detail_labels_related_purchase_type(app, client):
    main = Product(name="Ração", price=100, stock=2, status="active", is_demo=False)
    related = Product(
        name="Tapete por assinatura",
        price=40,
        stock=3,
        status="active",
        is_demo=False,
        subscription_enabled=True,
    )
    db.session.add_all([main, related])
    db.session.commit()

    response = client.get(f"/produto/{main.id}")
    body = response.data.decode()
    assert response.status_code == 200
    assert "Também pode ser útil" in body
    assert "Tapete por assinatura" in body
    assert "Compra ou assinatura" in body
