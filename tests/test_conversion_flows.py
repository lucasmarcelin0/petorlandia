"""Regressões dos fluxos públicos que levam cadastro a receita."""

from datetime import timedelta

import flask_login.utils as login_utils

from extensions import db
from models import (
    Clinica,
    User,
    Veterinario,
    VeterinarianMembership,
    VeterinarianMembershipSubscription,
    WaitlistLead,
)
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


def test_home_unifica_os_perfis_e_nao_expoe_preco_de_clinica_ao_tutor(client):
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Uma plataforma. Toda a rede de cuidado." in html
    assert "Sou tutor" in html
    assert "Tenho clínica" in html
    assert "Sou veterinário" in html
    assert "Sou estudante" in html
    assert "Grátis para tutores" in html
    assert "R$ 60/mês por veterinário" not in html


def test_home_carrega_fragmento_especifico_sem_misturar_precos(client):
    tutor = client.get("/inicio/perfil/tutor")
    clinic = client.get("/inicio/perfil/clinica")

    assert tutor.status_code == 200
    assert "Grátis para tutores" in tutor.get_data(as_text=True)
    assert "R$ 60/mês por veterinário" not in tutor.get_data(as_text=True)
    assert clinic.status_code == 200
    assert "R$ 60/mês por veterinário" in clinic.get_data(as_text=True)


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
    assert "/estudantes/area-profissional" in html
    assert "Área profissional" in html


def test_estudante_acompanha_fluxo_completo_em_ambiente_ficticio(app, client):
    student = User(
        name="Bruno Estudante",
        email="bruno.estudante@example.com",
        worker="estudante",
    )
    student.set_password("segredo123")
    db.session.add(student)
    db.session.commit()

    with client.session_transaction() as session:
        session["_user_id"] = str(student.id)
        session["_fresh"] = True

    response = client.get("/estudantes/pratica")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Área profissional · modo estudante" in html
    assert "Paciente fictício" in html
    assert "Somente leitura" in html
    assert "Sem doses ou prescrições" in html
    assert "Acolhimento" in html
    assert "Alta e continuidade" in html

    area = client.get("/estudantes/area-profissional")
    assert area.status_code == 200
    assert "Área profissional" in area.get_data(as_text=True)

    stage = client.get("/estudantes/pratica/etapa/raciocinio")
    assert stage.status_code == 200
    assert "Lista de problemas e raciocínio clínico" in stage.get_data(as_text=True)


def test_login_de_estudante_promove_conta_legada_para_area_educacional(app, client):
    legacy = User(name="Conta Legada", email="legada@example.com")
    legacy.set_password("segredo123")
    db.session.add(legacy)
    db.session.commit()

    response = client.post(
        "/login",
        data={
            "login": "legada@example.com",
            "password": "segredo123",
            "audience": "student",
            "next": "/estudantes/pratica",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/estudantes/pratica")
    assert db.session.get(User, legacy.id).worker == "estudante"


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


def test_checkout_veterinario_limita_reason_do_mercado_pago(app, client, monkeypatch):
    import app as app_module

    user = _user()
    user.name = "Dra. " + ("Nome Profissional Muito Longo " * 5)
    vet = Veterinario(user=user, crmv="12345", crmv_estado="SP")
    db.session.add(vet)
    db.session.commit()
    _login(monkeypatch, user)

    captured = {}

    class FakePreapproval:
        def create(self, payload):
            captured.update(payload)
            return {
                "status": 201,
                "response": {
                    "id": "pre-vet-1",
                    "init_point": "https://mp.example/assinatura",
                },
            }

    class FakeSDK:
        def preapproval(self):
            return FakePreapproval()

    monkeypatch.setattr(app_module, "mp_sdk", lambda: FakeSDK())

    response = client.post(
        "/veterinario/assinatura/checkout",
        data={"plano": "mensal"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "https://mp.example/assinatura"
    assert 1 <= len(captured["reason"]) <= 60
    assert captured["reason"] == "Assinatura PetOrlandia (mensal)"
    assert user.name not in captured["reason"]
    attempt = VeterinarianMembershipSubscription.query.one()
    assert captured["external_reference"] == attempt.external_reference
    assert attempt.provider_preapproval_id == "pre-vet-1"
    assert attempt.status == "pending"


def test_checkout_veterinario_reabre_preapproval_pendente_sem_cancelar(
    app, client, monkeypatch
):
    import app as app_module

    user = _user("retomar@example.com")
    vet = Veterinario(user=user, crmv="54321", crmv_estado="SP")
    db.session.add(vet)
    db.session.commit()
    membership = VeterinarianMembership.query.filter_by(veterinario_id=vet.id).one()
    membership.preapproval_id = "pre-pending"
    db.session.commit()
    _login(monkeypatch, user)

    calls = []

    class FakePreapproval:
        def get(self, preapproval_id):
            calls.append(("get", preapproval_id))
            return {
                "status": 200,
                "response": {
                    "id": preapproval_id,
                    "status": "pending",
                    "external_reference": f"vet-membership-{membership.id}-legacy-mensal",
                    "init_point": "https://mp.example/continuar",
                    "auto_recurring": {
                        "transaction_amount": 60,
                        "currency_id": "BRL",
                    },
                },
            }

        def update(self, preapproval_id, payload):
            raise AssertionError("preapproval pending não deve ser cancelado")

        def create(self, payload):
            raise AssertionError("não deve criar assinatura duplicada")

    class FakeSDK:
        def preapproval(self):
            return FakePreapproval()

    monkeypatch.setattr(app_module, "mp_sdk", lambda: FakeSDK())

    response = client.post(
        "/veterinario/assinatura/checkout",
        data={"plano": "mensal"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "https://mp.example/continuar"
    assert calls == [("get", "pre-pending")]
    assert VeterinarianMembershipSubscription.query.count() == 1


def test_checkout_admin_sem_perfil_nao_cria_assinatura_orfa(
    app, client, monkeypatch
):
    import app as app_module

    admin = _user("admin-sem-vet@example.com")
    admin.role = "admin"
    db.session.commit()
    _login(monkeypatch, admin)

    monkeypatch.setattr(
        app_module,
        "mp_sdk",
        lambda: (_ for _ in ()).throw(
            AssertionError("Mercado Pago não deve ser chamado sem membership")
        ),
    )

    response = client.post(
        "/veterinario/assinatura/checkout",
        data={"plano": "mensal"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/veterinario/assinatura")
    assert VeterinarianMembershipSubscription.query.count() == 0


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
            return {"status": 200, "response": {"status": "canceled"}}

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
        assert calls == [("pre-123", {"status": "canceled"})]


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
