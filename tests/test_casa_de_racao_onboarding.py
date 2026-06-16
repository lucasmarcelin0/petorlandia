import hashlib
from datetime import datetime, timedelta, timezone

from extensions import db
from models import CasaDeRacao, CasaDeRacaoOnboardingInvite, Product, User


def _setup_invite():
    owner = User(
        name="Sabrina Agrograner",
        email="temporary@convite.petorlandia.local",
        phone="+553492013165",
    )
    owner.set_password("temporary-secret")
    db.session.add(owner)
    db.session.flush()

    casa = CasaDeRacao(
        nome="AgroGraner",
        owner_id=owner.id,
        status="pendente",
        modo_entrega="plataforma",
        valor_frete=0,
    )
    db.session.add(casa)
    db.session.flush()

    products = [
        Product(
            name="Simparic",
            price=0,
            stock=0,
            status="inactive",
            casa_de_racao_id=casa.id,
        ),
        Product(
            name="Canex Original",
            price=0,
            stock=0,
            status="inactive",
            casa_de_racao_id=casa.id,
        ),
    ]
    db.session.add_all(products)

    token = "private-onboarding-token"
    invite = CasaDeRacaoOnboardingInvite(
        casa_de_racao_id=casa.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.session.add(invite)
    db.session.commit()
    return token, owner.id, casa.id, [product.id for product in products], invite.id


def test_store_onboarding_completes_account_and_catalog(app, client):
    with app.app_context():
        token, owner_id, casa_id, product_ids, invite_id = _setup_invite()

    response = client.get(f"/ativar-loja/{token}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Vamos deixar sua loja pronta" in html
    assert "Voce nao precisa preencher tudo de uma vez" in html

    response = client.post(
        f"/ativar-loja/{token}",
        data={
            "owner_name": "Sabrina Silva",
            "email": "sabrina@example.com",
            "phone": "(34) 99201-3165",
            "store_name": "AgroGraner",
            "store_email": "contato@agrograner.com",
            "address": "Rua Central, 10, Uberlandia - MG",
            "modo_entrega": "propria",
            "password": "senha-segura",
            "password_confirmation": "senha-segura",
            f"price_{product_ids[0]}": "89,90",
            f"stock_{product_ids[0]}": "5",
            f"price_{product_ids[1]}": "",
            f"stock_{product_ids[1]}": "",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/casa-de-racao/{casa_id}")

    with app.app_context():
        owner = db.session.get(User, owner_id)
        casa = db.session.get(CasaDeRacao, casa_id)
        invite = db.session.get(CasaDeRacaoOnboardingInvite, invite_id)
        products = Product.query.filter(Product.id.in_(product_ids)).all()
        by_name = {product.name: product for product in products}

        assert owner.email == "sabrina@example.com"
        assert owner.phone == "+5534992013165"
        assert owner.check_password("senha-segura")
        assert casa.status == "ativa"
        assert casa.modo_entrega == "propria"
        assert invite.used_at is not None
        assert by_name["Simparic"].status == "active"
        assert by_name["Simparic"].price == 89.9
        assert by_name["Simparic"].stock == 5
        assert by_name["Canex Original"].status == "inactive"
        assert by_name["Canex Original"].price == 0
        assert by_name["Canex Original"].stock == 0

    reused = client.get(f"/ativar-loja/{token}")
    assert reused.status_code == 302
    assert reused.headers["Location"].endswith("/login")


def test_store_onboarding_requires_at_least_one_product(app, client):
    with app.app_context():
        token, _, casa_id, product_ids, _ = _setup_invite()

    response = client.post(
        f"/ativar-loja/{token}",
        data={
            "owner_name": "Sabrina Silva",
            "email": "sabrina@example.com",
            "phone": "(34) 99201-3165",
            "store_name": "AgroGraner",
            "address": "Rua Central, 10, Uberlandia - MG",
            "modo_entrega": "plataforma",
            "password": "senha-segura",
            "password_confirmation": "senha-segura",
            f"price_{product_ids[0]}": "",
            f"stock_{product_ids[0]}": "",
            f"price_{product_ids[1]}": "",
            f"stock_{product_ids[1]}": "",
        },
    )
    assert response.status_code == 200
    assert "ao menos um produto" in response.get_data(as_text=True)

    with app.app_context():
        assert db.session.get(CasaDeRacao, casa_id).status == "pendente"
        assert Product.query.filter_by(casa_de_racao_id=casa_id, status="active").count() == 0


def test_store_onboarding_prefills_store_email_from_owner_email(app, client):
    with app.app_context():
        token, owner_id, _, _, _ = _setup_invite()
        owner = db.session.get(User, owner_id)
        owner.email = "sabrina@example.com"
        db.session.commit()

    response = client.get(f"/ativar-loja/{token}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'value="sabrina@example.com"' in html
