"""Usability-oriented tests for the main PetOrlandia user journeys.

The goal here is to catch breakages that regular users experience as "the
button does nothing": dead links, invalid form actions, unnamed icon buttons,
and critical account/delivery flows returning confusing server errors.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urljoin, urlparse

import pytest
from bs4 import BeautifulSoup
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import RequestRedirect

import app as app_module
from extensions import db
from models import (
    Animal,
    BlocoOrcamento,
    BlocoPrescricao,
    Breed,
    Clinica,
    DeliveryRequest,
    Endereco,
    Order,
    OrderItem,
    OrcamentoItem,
    PickupLocation,
    Prescricao,
    Product,
    Species,
    User,
    Veterinario,
)
from models.base import ClinicStaff


PASSWORD = "Senha@123"


def _login(client, user_id: int) -> None:
    with client.application.app_context():
        user = db.session.get(User, user_id)
        assert user is not None
        email = user.email
    response = client.post(
        "/login",
        data={"email": email, "password": PASSWORD, "remember": "y"},
        follow_redirects=False,
    )
    assert response.status_code in {200, 302}


def _logout(client) -> None:
    with client.session_transaction() as sess:
        sess.clear()


def _make_user(email: str, name: str, role: str = "adotante", worker: str | None = None) -> User:
    user = User(name=name, email=email, role=role, worker=worker, phone="16999990000")
    user.set_password(PASSWORD)
    return user


def _assert_internal_route_resolves(app, raw_url: str, method: str, source: str) -> None:
    if not raw_url:
        raw_url = source

    parsed = urlparse(urljoin("http://localhost/", raw_url))
    if parsed.scheme not in {"http", "https"} or parsed.netloc not in {"localhost", ""}:
        return

    path = parsed.path or "/"
    if path.startswith("/static/") or path in {"/service-worker.js"}:
        return

    adapter = app.url_map.bind("localhost")
    try:
        adapter.match(path, method=method.upper())
    except RequestRedirect:
        return
    except MethodNotAllowed as exc:
        pytest.fail(f"{source}: {raw_url} existe, mas não aceita {method.upper()} ({exc})")
    except NotFound:
        pytest.fail(f"{source}: rota interna não encontrada para {raw_url}")


def _assert_buttons_have_accessible_names(soup: BeautifulSoup, source: str) -> None:
    for button in soup.find_all("button"):
        text = " ".join(button.get_text(" ", strip=True).split())
        accessible_name = (
            text
            or button.get("aria-label")
            or button.get("title")
            or button.get("value")
            or button.get("aria-labelledby")
        )
        assert accessible_name, f"{source}: botão sem nome acessível: {button}"


def _assert_forms_have_valid_actions(app, soup: BeautifulSoup, source: str) -> None:
    for form in soup.find_all("form"):
        method = (form.get("method") or "get").lower()
        assert method in {"get", "post"}, f"{source}: formulário com método inválido: {method}"

        action = form.get("action") or source
        if action.startswith("#"):
            action = source
        _assert_internal_route_resolves(app, action, method, source)

        submit_controls = [
            tag
            for tag in form.find_all(["button", "input"])
            if tag.name == "button"
            or (tag.name == "input" and (tag.get("type") or "submit").lower() in {"submit", "button", "image"})
        ]
        if form.find_all(["input", "select", "textarea"]):
            assert submit_controls or form.get("data-appointment-form") is not None, (
                f"{source}: formulário sem controle claro de envio"
            )


def _assert_links_resolve(app, soup: BeautifulSoup, source: str) -> None:
    ignored_prefixes = ("#", "javascript:", "mailto:", "tel:", "data:")
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if not href or href.startswith(ignored_prefixes):
            continue
        _assert_internal_route_resolves(app, href, "GET", source)


def _assert_bootstrap_targets_exist(soup: BeautifulSoup, source: str) -> None:
    for element in soup.select("[data-bs-target]"):
        target = element.get("data-bs-target", "")
        if target.startswith("#") and target != "#":
            assert soup.find(id=target[1:]) is not None, (
                f"{source}: controle aponta para alvo inexistente {target}"
            )


def _assert_page_controls_are_usable(app, response, source: str) -> None:
    assert response.status_code == 200, (
        f"{source}: esperado 200, recebeu {response.status_code}; "
        f"Location={response.headers.get('Location')}"
    )
    soup = BeautifulSoup(response.data, "html.parser")
    _assert_buttons_have_accessible_names(soup, source)
    _assert_forms_have_valid_actions(app, soup, source)
    _assert_links_resolve(app, soup, source)
    _assert_bootstrap_targets_exist(soup, source)


@pytest.fixture()
def usability_seed(app):
    with app.app_context():
        tutor = _make_user("tutor.usabilidade@test.com", "Tutora Usabilidade")
        tutor.endereco = Endereco(
            cep="14620-000",
            rua="Rua Teste",
            numero="100",
            bairro="Centro",
            cidade="Orlandia",
            estado="SP",
            latitude=-20.72,
            longitude=-47.88,
        )
        delivery = _make_user("delivery.usabilidade@test.com", "Entregador Usabilidade", worker="delivery")
        admin = _make_user("admin.usabilidade@test.com", "Admin Usabilidade", role="admin")
        vet_user = _make_user(
            "vet.usabilidade@test.com",
            "Dra Usabilidade",
            role="veterinario",
            worker="veterinario",
        )
        collaborator = _make_user(
            "colab.usabilidade@test.com",
            "Colab Usabilidade",
            worker="colaborador",
        )
        other_tutor = _make_user("outro.tutor.usabilidade@test.com", "Outro Tutor")
        db.session.add_all([tutor, delivery, admin, vet_user, collaborator, other_tutor])
        db.session.commit()

        clinic = Clinica(
            nome="Clinica Usabilidade",
            cnpj="12.345.678/0001-90",
            endereco="Rua da Clinica, 10",
            telefone="1633334444",
            email="clinica.usabilidade@test.com",
            owner_id=vet_user.id,
        )
        db.session.add(clinic)
        db.session.commit()

        vet_user.clinica_id = clinic.id
        collaborator.clinica_id = clinic.id
        vet_profile = Veterinario(user_id=vet_user.id, crmv="CRMV-SP 12345", clinica_id=clinic.id)
        db.session.add(vet_profile)
        db.session.add(
            ClinicStaff(
                clinic_id=clinic.id,
                user_id=collaborator.id,
                can_manage_clients=True,
                can_manage_animals=True,
                can_manage_schedule=True,
                can_manage_inventory=True,
                can_view_full_calendar=True,
            )
        )

        species = Species(name="Cachorro")
        db.session.add(species)
        db.session.flush()
        breed = Breed(name="SRD", species_id=species.id)
        db.session.add(breed)
        db.session.flush()
        animal = Animal(
            name="Rex Usabilidade",
            species_id=species.id,
            breed_id=breed.id,
            user_id=tutor.id,
            sex="Macho",
            status="disponivel",
            clinica_id=clinic.id,
        )
        db.session.add(animal)

        product = Product(name="Racao Teste", description="Produto de teste", price=50.0, stock=10)
        pickup_address = Endereco(
            cep="14620-000",
            rua="Rua Retirada",
            numero="1",
            cidade="Orlandia",
            estado="SP",
        )
        pickup = PickupLocation(nome="Retirada Central", endereco=pickup_address, ativo=True)
        db.session.add_all([product, pickup_address, pickup])
        db.session.flush()

        budget = BlocoOrcamento(
            animal_id=animal.id,
            clinica_id=clinic.id,
            payment_status="pending",
        )
        db.session.add(budget)
        db.session.flush()
        db.session.add(
            OrcamentoItem(
                bloco_id=budget.id,
                descricao="Consulta de bem-estar",
                valor=Decimal("150.00"),
                clinica_id=clinic.id,
            )
        )

        prescription_block = BlocoPrescricao(
            animal_id=animal.id,
            clinica_id=clinic.id,
            saved_by_id=vet_user.id,
        )
        db.session.add(prescription_block)
        db.session.flush()
        db.session.add(
            Prescricao(
                bloco_id=prescription_block.id,
                animal_id=animal.id,
                medicamento="Medicamento de teste",
                dosagem="5 mg",
                frequencia="1x ao dia",
                duracao="7 dias",
            )
        )

        orders = []
        for index in range(3):
            order = Order(user_id=tutor.id, shipping_address=f"Rua Entrega, {index}")
            db.session.add(order)
            db.session.flush()
            db.session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    item_name=product.name,
                    quantity=1,
                    unit_price=product.price,
                )
            )
            orders.append(order)

        pending_req = DeliveryRequest(
            order_id=orders[0].id,
            requested_by_id=tutor.id,
            status="pendente",
            pickup=pickup,
        )
        doing_req = DeliveryRequest(
            order_id=orders[1].id,
            requested_by_id=tutor.id,
            status="em_andamento",
            worker_id=delivery.id,
            pickup=pickup,
            accepted_at=datetime.utcnow(),
        )
        cancel_req = DeliveryRequest(
            order_id=orders[2].id,
            requested_by_id=tutor.id,
            status="em_andamento",
            worker_id=delivery.id,
            pickup=pickup,
            accepted_at=datetime.utcnow(),
        )
        db.session.add_all([pending_req, doing_req, cancel_req])
        db.session.commit()

        return {
            "tutor_id": tutor.id,
            "delivery_id": delivery.id,
            "admin_id": admin.id,
            "vet_id": vet_user.id,
            "collaborator_id": collaborator.id,
            "other_tutor_id": other_tutor.id,
            "clinic_id": clinic.id,
            "animal_id": animal.id,
            "budget_id": budget.id,
            "prescription_block_id": prescription_block.id,
            "pending_req_id": pending_req.id,
            "doing_req_id": doing_req.id,
            "cancel_req_id": cancel_req.id,
        }


def test_account_registration_login_and_password_reset_do_not_dead_end(client, app, monkeypatch):
    response = client.get("/register")
    _assert_page_controls_are_usable(app, response, "/register")

    registration_data = {
        "name": "Cliente Jornada",
        "email": "cliente.jornada@test.com",
        "phone": "16999998888",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
        "cep": "14620-000",
        "rua": "Rua Cadastro",
        "numero": "42",
        "bairro": "Centro",
        "cidade": "Orlandia",
        "estado": "SP",
        "latitude": "-20.7200",
        "longitude": "-47.8800",
    }
    response = client.post(
        "/register",
        data=registration_data,
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.get_json()["redirect"] == "/"

    with app.app_context():
        user = User.query.filter_by(email=registration_data["email"]).first()
        assert user is not None
        assert user.endereco is not None
        assert user.check_password(PASSWORD)

    _logout(client)
    duplicate = client.post(
        "/register",
        data=registration_data,
        headers={"Accept": "application/json"},
    )
    assert duplicate.status_code == 400
    assert "email" in duplicate.get_json()["errors"]

    invalid_login = client.post(
        "/login",
        data={"email": registration_data["email"], "password": "senha-errada"},
        headers={"Accept": "application/json"},
    )
    assert invalid_login.status_code == 400
    assert invalid_login.get_json()["message"]

    valid_login = client.post(
        "/login",
        data={"email": registration_data["email"], "password": PASSWORD, "remember": "y"},
        headers={"Accept": "application/json"},
    )
    assert valid_login.status_code == 200
    assert valid_login.get_json()["redirect"] == "/"

    _logout(client)

    def _smtp_unavailable(_message):
        raise RuntimeError("SMTP indisponivel no teste")

    monkeypatch.setattr(app_module.mail, "send", _smtp_unavailable)
    reset_response = client.post(
        "/reset_password_request",
        data={"email": registration_data["email"]},
        follow_redirects=True,
    )
    assert reset_response.status_code == 200
    assert "Não foi possível enviar".encode("utf-8") in reset_response.data


def test_profile_rejects_incomplete_address_without_server_error(client, app, usability_seed):
    _login(client, usability_seed["tutor_id"])

    response = client.post(
        "/profile",
        data={
            "name": "Tutora Usabilidade",
            "email": "tutor.usabilidade@test.com",
            "phone": "16999990000",
            "rua": "Rua Sem CEP",
            "cidade": "Orlandia",
            "estado": "SP",
            "photo_rotation": "0",
            "photo_zoom": "1.0",
            "photo_offset_x": "0",
            "photo_offset_y": "0",
        },
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 400
    assert "endereco" in response.get_json()["errors"]

    with app.app_context():
        user = db.session.get(User, usability_seed["tutor_id"])
        assert user.endereco.cep == "14620-000"
        assert user.endereco.rua == "Rua Teste"


def test_rendered_pages_keep_links_forms_and_buttons_usable_for_all_roles(client, app, usability_seed):
    scenarios = [
        ("visitante", None, ["/", "/login", "/register", "/reset_password_request"]),
        (
            "tutor",
            usability_seed["tutor_id"],
            ["/", "/animals", "/add-animal", "/profile", f"/animal/{usability_seed['animal_id']}/ficha"],
        ),
        (
            "entregador",
            usability_seed["delivery_id"],
            ["/", "/delivery_requests", f"/delivery/{usability_seed['doing_req_id']}"],
        ),
        (
            "veterinario",
            usability_seed["vet_id"],
            ["/", "/appointments", "/minha-clinica", f"/clinica/{usability_seed['clinic_id']}"],
        ),
        (
            "colaborador",
            usability_seed["collaborator_id"],
            ["/", "/appointments", f"/clinica/{usability_seed['clinic_id']}/dashboard"],
        ),
        (
            "admin",
            usability_seed["admin_id"],
            ["/", "/admin/delivery_overview", "/admin/delivery_archive"],
        ),
    ]

    for role_name, user_id, paths in scenarios:
        for path in paths:
            _logout(client)
            if user_id is not None:
                _login(client, user_id)
            response = client.get(path, follow_redirects=True)
            if user_id is not None:
                assert not response.request.path.startswith("/login"), (
                    f"{role_name}:{path}: usuário autenticado foi enviado para login"
                )
            _assert_page_controls_are_usable(app, response, f"{role_name}:{path}")


def test_tutor_can_view_own_budget_and_prescription_but_other_tutors_cannot(client, usability_seed):
    _login(client, usability_seed["tutor_id"])

    budget = client.get(f"/imprimir_bloco_orcamento/{usability_seed['budget_id']}")
    assert budget.status_code == 200
    budget_text = budget.data.decode("utf-8")
    assert "Rex Usabilidade" in budget_text
    assert "Consulta de bem-estar" in budget_text
    assert "150.00" in budget_text

    prescription = client.get(f"/bloco_prescricao/{usability_seed['prescription_block_id']}/imprimir")
    assert prescription.status_code == 200
    prescription_text = prescription.data.decode("utf-8")
    assert "Rex Usabilidade" in prescription_text
    assert "Medicamento de teste" in prescription_text
    assert "Dra Usabilidade" in prescription_text

    _logout(client)
    _login(client, usability_seed["other_tutor_id"])
    assert client.get(f"/imprimir_bloco_orcamento/{usability_seed['budget_id']}").status_code in {403, 404}
    assert client.get(f"/bloco_prescricao/{usability_seed['prescription_block_id']}/imprimir").status_code in {403, 404}


def test_tutor_direct_appointment_post_redirects_to_veterinarian_selection(client, usability_seed):
    _login(client, usability_seed["tutor_id"])

    response = client.post(
        "/appointments",
        data={
            "animal_id": usability_seed["animal_id"],
            "clinica_id": usability_seed["clinic_id"],
            "data_hora": (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "tipo": "consulta",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/veterinarios" in response.headers["Location"]


def test_delivery_buttons_move_requests_through_expected_states(client, app, usability_seed):
    _login(client, usability_seed["delivery_id"])

    page = client.get("/delivery_requests")
    _assert_page_controls_are_usable(app, page, "/delivery_requests")
    assert "Aceitar".encode("utf-8") in page.data

    headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    accepted = client.post(f"/delivery_requests/{usability_seed['pending_req_id']}/accept", headers=headers)
    assert accepted.status_code == 200
    payload = accepted.get_json()
    assert payload["message"] == "Entrega aceita."
    assert payload["counts"]["doing"] >= 2

    with app.app_context():
        req = db.session.get(DeliveryRequest, usability_seed["pending_req_id"])
        assert req.status == "em_andamento"
        assert req.worker_id == usability_seed["delivery_id"]

    completed = client.post(f"/delivery_requests/{usability_seed['pending_req_id']}/complete", headers=headers)
    assert completed.status_code == 200
    assert completed.get_json()["message"] == "Entrega concluída."

    with app.app_context():
        req = db.session.get(DeliveryRequest, usability_seed["pending_req_id"])
        assert req.status == "concluida"
        assert req.completed_at is not None

    canceled = client.post(f"/delivery_requests/{usability_seed['cancel_req_id']}/cancel", headers=headers)
    assert canceled.status_code == 200
    assert canceled.get_json()["message"] == "Entrega cancelada."

    with app.app_context():
        req = db.session.get(DeliveryRequest, usability_seed["cancel_req_id"])
        assert req.status == "cancelada"
        assert req.canceled_by_id == usability_seed["delivery_id"]
