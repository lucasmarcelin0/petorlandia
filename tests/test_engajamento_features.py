"""Testes dos recursos de engajamento: Web Push, carteirinha e assinatura de ração."""
import flask_login.utils as login_utils

from extensions import db
from models import Animal, PushSubscription, RacaoAssinatura, User, Vacina


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def _make_user(email="tutor@test.com", role="adotante"):
    user = User(name="Tutor Teste", email=email, role=role)
    user.set_password("x") if hasattr(user, "set_password") else setattr(user, "password_hash", "x")
    db.session.add(user)
    db.session.commit()
    return user


def _make_animal(user, name="Rex"):
    animal = Animal(name=name, user_id=user.id, modo="pessoal")
    db.session.add(animal)
    db.session.commit()
    return animal


# ── Web Push ────────────────────────────────────────────────────────────────

def test_vapid_public_key_disabled_by_default(client):
    resp = client.get("/push/vapid-public-key")
    assert resp.status_code == 200
    assert resp.get_json()["enabled"] is False


def test_push_subscribe_and_unsubscribe(app, client, monkeypatch):
    user = _make_user()
    _login(monkeypatch, user)

    sub_payload = {
        "subscription": {
            "endpoint": "https://push.example.com/abc123",
            "keys": {"p256dh": "chave-p256dh", "auth": "chave-auth"},
        }
    }
    resp = client.post("/push/subscribe", json=sub_payload)
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert PushSubscription.query.filter_by(user_id=user.id).count() == 1

    # idempotente: repetir atualiza em vez de duplicar
    resp = client.post("/push/subscribe", json=sub_payload)
    assert resp.status_code == 200
    assert PushSubscription.query.filter_by(user_id=user.id).count() == 1

    resp = client.post(
        "/push/unsubscribe", json={"endpoint": "https://push.example.com/abc123"}
    )
    assert resp.status_code == 200
    assert PushSubscription.query.filter_by(user_id=user.id).count() == 0


def test_push_subscribe_rejects_incomplete(app, client, monkeypatch):
    user = _make_user()
    _login(monkeypatch, user)
    resp = client.post("/push/subscribe", json={"subscription": {"endpoint": "x"}})
    assert resp.status_code == 400


def test_push_to_user_noop_without_keys(app):
    from services.push import push_to_user

    user = _make_user()
    assert push_to_user(user.id, "t", "b") == 0


# ── Carteirinha digital ─────────────────────────────────────────────────────

def test_carteirinha_fluxo_completo(app, client, monkeypatch):
    user = _make_user()
    animal = _make_animal(user)
    _login(monkeypatch, user)

    # ativa
    resp = client.post(f"/animal/{animal.id}/carteirinha/ativar")
    assert resp.status_code == 302
    db.session.refresh(animal)
    assert animal.public_token

    # página pública acessível sem login
    from flask_login import AnonymousUserMixin
    monkeypatch.setattr(login_utils, "_get_user", lambda: AnonymousUserMixin())
    resp = client.get(f"/carteirinha/{animal.public_token}")
    assert resp.status_code == 200
    assert b"Rex" in resp.data

    # QR responde PNG
    resp = client.get(f"/carteirinha/{animal.public_token}/qr.png")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"

    # desativa → link morre
    token = animal.public_token
    _login(monkeypatch, user)
    resp = client.post(f"/animal/{animal.id}/carteirinha/desativar")
    assert resp.status_code == 302
    db.session.refresh(animal)
    assert animal.public_token is None
    resp = client.get(f"/carteirinha/{token}")
    assert resp.status_code == 404


def test_carteirinha_apenas_dono_gerencia(app, client, monkeypatch):
    dono = _make_user()
    outro = _make_user(email="outro@test.com")
    animal = _make_animal(dono)
    _login(monkeypatch, outro)
    resp = client.post(f"/animal/{animal.id}/carteirinha/ativar")
    assert resp.status_code in (403, 404)


def test_carteirinha_mostra_vacinas(app, client, monkeypatch):
    from datetime import date

    user = _make_user()
    animal = _make_animal(user)
    db.session.add(Vacina(
        animal_id=animal.id, nome="Antirrábica", aplicada=True,
        aplicada_em=date(2026, 5, 1),
    ))
    db.session.commit()
    _login(monkeypatch, user)
    client.post(f"/animal/{animal.id}/carteirinha/ativar")
    db.session.refresh(animal)

    from flask_login import AnonymousUserMixin
    monkeypatch.setattr(login_utils, "_get_user", lambda: AnonymousUserMixin())
    resp = client.get(f"/carteirinha/{animal.public_token}")
    assert "Antirrábica".encode() in resp.data


# ── Assinatura de ração ─────────────────────────────────────────────────────

def _make_product(price=50.0):
    from models import Product

    prod = Product(name="Ração Premium 15kg", price=price, stock=10, status="active")
    db.session.add(prod)
    db.session.commit()
    return prod


def test_assinatura_pagina_form(app, client, monkeypatch):
    user = _make_user()
    prod = _make_product()
    _login(monkeypatch, user)
    resp = client.get(f"/produto/{prod.id}/assinar")
    assert resp.status_code == 200
    assert "Assinar".encode() in resp.data


def test_assinatura_cria_e_redireciona_mp(app, client, monkeypatch):
    import app as app_module

    user = _make_user()
    prod = _make_product()
    _login(monkeypatch, user)

    class FakePreapproval:
        def create(self, data):
            assert data["external_reference"].startswith("racao-assinatura-")
            assert data["auto_recurring"]["transaction_amount"] > 0
            return {
                "status": 201,
                "response": {"id": "pre-123", "init_point": "https://mp.example/init"},
            }

    class FakeSDK:
        def preapproval(self):
            return FakePreapproval()

    monkeypatch.setattr(app_module, "mp_sdk", lambda: FakeSDK())

    resp = client.post(
        f"/produto/{prod.id}/assinar",
        data={"frequencia_dias": "30", "quantidade": "1"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://mp.example/init"

    sub = RacaoAssinatura.query.filter_by(user_id=user.id).first()
    assert sub is not None
    assert sub.status == "pending"
    assert sub.mp_preapproval_id == "pre-123"


def test_assinatura_ciclo_ativa_e_conta(app, monkeypatch):
    from blueprints.loja import _process_racao_assinatura_ciclo

    user = _make_user()
    prod = _make_product()
    sub = RacaoAssinatura(
        user_id=user.id, product_id=prod.id, quantidade=1,
        frequencia_dias=30, preco_ciclo=55, status="pending",
    )
    db.session.add(sub)
    db.session.commit()

    _process_racao_assinatura_ciclo(sub, mp_id="pre-9")
    db.session.commit()
    assert sub.status == "active"
    assert sub.ciclos_pagos == 1
    assert sub.activated_at is not None

    _process_racao_assinatura_ciclo(sub)
    db.session.commit()
    assert sub.ciclos_pagos == 2


def test_assinatura_cancelar(app, client, monkeypatch):
    import app as app_module

    user = _make_user()
    prod = _make_product()
    sub = RacaoAssinatura(
        user_id=user.id, product_id=prod.id, quantidade=1,
        frequencia_dias=30, preco_ciclo=55, status="active",
        mp_preapproval_id="pre-1",
    )
    db.session.add(sub)
    db.session.commit()
    _login(monkeypatch, user)

    cancelled = {}

    class FakePreapproval:
        def update(self, pid, data):
            cancelled[pid] = data
            return {"status": 200}

    class FakeSDK:
        def preapproval(self):
            return FakePreapproval()

    monkeypatch.setattr(app_module, "mp_sdk", lambda: FakeSDK())

    resp = client.post(f"/assinatura-racao/{sub.id}/cancelar")
    assert resp.status_code == 302
    assert sub.status == "cancelled"
    assert cancelled == {"pre-1": {"status": "cancelled"}}


def test_minhas_assinaturas_lista(app, client, monkeypatch):
    user = _make_user()
    prod = _make_product()
    db.session.add(RacaoAssinatura(
        user_id=user.id, product_id=prod.id, quantidade=2,
        frequencia_dias=30, preco_ciclo=110, status="active",
    ))
    db.session.commit()
    _login(monkeypatch, user)
    resp = client.get("/minhas-assinaturas-racao")
    assert resp.status_code == 200
    assert "Ração Premium".encode() in resp.data
