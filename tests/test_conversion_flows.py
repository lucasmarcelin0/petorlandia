"""Regressões dos fluxos públicos que levam cadastro a receita."""

from datetime import timedelta

import flask_login.utils as login_utils

from extensions import db
from models import Clinica, User, Veterinario, VeterinarianMembership, WaitlistLead
from time_utils import utcnow


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def _user(email="vet@example.com"):
    user = User(name="Dra. Marina", email=email)
    user.set_password("segredo123")
    db.session.add(user)
    db.session.commit()
    return user


def test_register_preserva_destino_de_aquisicao(app, client):
    response = client.post(
        "/register",
        data={
            "name": "Marina Vet",
            "email": "marina.nova@example.com",
            "password": "segredo123",
            "next": "/minha-clinica",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/minha-clinica")


def test_porta_de_entrada_do_estudante_tem_login_e_cadastro_direcionado(app, client):
    response = client.get("/estudantes")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Entrar como estudante" in html
    assert 'name="audience" value="student"' in html
    assert "/register?next=/estudantes&amp;audience=student" in html


def test_cadastro_de_estudante_volta_para_hub_gratuito(app, client):
    response = client.post(
        "/register",
        data={
            "name": "Ana Estudante",
            "email": "ana.estudante@example.com",
            "password": "segredo123",
            "next": "/estudantes",
            "audience": "student",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/estudantes")
    student = User.query.filter_by(email="ana.estudante@example.com").one()
    assert student.worker == "estudante"

    hub = client.get("/estudantes")
    html = hub.get_data(as_text=True)
    assert hub.status_code == 200
    assert "Biblioteca educacional" in html
    assert 'href="/estudantes"' in html
    assert "Estudar" in html
    assert "Uso responsável" in html


def test_ativacao_da_clinica_cria_veterinario_e_avaliacao(app, client, monkeypatch):
    with app.app_context():
        user = _user()
        _login(monkeypatch, user)

        response = client.post(
            "/minha-clinica",
            data={
                "nome": "Clínica Conversão",
                "sou_veterinario": "y",
                "crmv": "12345",
                "crmv_estado": "SP",
            },
        )

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/veterinario/assinatura")
        clinic = Clinica.query.filter_by(nome="Clínica Conversão").one()
        vet = Veterinario.query.filter_by(user_id=user.id).one()
        assert clinic.status == "pendente"
        assert vet.clinica_id == clinic.id
        assert vet.crmv == "12345"
        assert vet.crmv_estado == "SP"
        assert vet.membership is not None
        assert vet.membership.is_trial_active()


def test_demo_funciona_sem_whatsapp_configurado(app, client):
    response = client.post(
        "/lista-de-espera",
        json={
            "feature": "demo_clinica",
            "contact": "marina@clinica.com.br",
            "city": "Orlândia",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    with app.app_context():
        lead = WaitlistLead.query.filter_by(feature="demo_clinica").one()
        assert lead.contact == "marina@clinica.com.br"
        assert lead.city == "Orlândia"


def test_cancelamento_confirma_no_provedor_antes_de_parar_renovacao(
    app, client, monkeypatch
):
    calls = []

    class FakePreapproval:
        def update(self, preapproval_id, payload):
            calls.append((preapproval_id, payload))
            return {"status": 200, "response": {"status": "cancelled"}}

    class FakeSdk:
        def preapproval(self):
            return FakePreapproval()

    with app.app_context():
        user = _user("assinante@example.com")
        vet = Veterinario(user=user, crmv="9001", crmv_estado="SP")
        db.session.add(vet)
        db.session.commit()
        membership = VeterinarianMembership.query.filter_by(veterinario_id=vet.id).one()
        membership.preapproval_id = "pre-123"
        membership.payment_method_set_at = utcnow()
        membership.paid_until = utcnow() + timedelta(days=20)
        db.session.commit()
        membership_id = membership.id
        _login(monkeypatch, user)

        import app as app_module

        monkeypatch.setattr(app_module, "mp_sdk", lambda: FakeSdk())
        response = client.post(
            f"/veterinario/assinatura/{membership_id}/cancelar-renovacao"
        )

        assert response.status_code == 302
        refreshed = db.session.get(VeterinarianMembership, membership_id)
        assert refreshed.preapproval_id is None
        assert refreshed.payment_method_set_at is None
        assert refreshed.has_valid_payment()
        assert calls == [("pre-123", {"status": "cancelled"})]


def test_falha_no_provedor_nao_finge_que_renovacao_foi_cancelada(
    app, client, monkeypatch
):
    class FailingPreapproval:
        def update(self, preapproval_id, payload):
            return {"status": 503, "response": {"message": "unavailable"}}

    class FakeSdk:
        def preapproval(self):
            return FailingPreapproval()

    with app.app_context():
        user = _user("falha@example.com")
        vet = Veterinario(user=user, crmv="9002", crmv_estado="SP")
        db.session.add(vet)
        db.session.commit()
        membership = VeterinarianMembership.query.filter_by(veterinario_id=vet.id).one()
        membership.preapproval_id = "pre-still-active"
        membership.payment_method_set_at = utcnow()
        db.session.commit()
        membership_id = membership.id
        _login(monkeypatch, user)

        import app as app_module

        monkeypatch.setattr(app_module, "mp_sdk", lambda: FakeSdk())
        response = client.post(
            f"/veterinario/assinatura/{membership_id}/cancelar-renovacao"
        )

        assert response.status_code == 302
        refreshed = db.session.get(VeterinarianMembership, membership_id)
        assert refreshed.preapproval_id == "pre-still-active"
        assert refreshed.has_payment_method()
