"""Regressões do upload de fotos de produto na Loja."""

import io

import flask_login.utils as login_utils

import app as app_module
from extensions import db
from models import Product, ProductPhoto, User


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def _admin():
    user = User(name="Admin Loja", email="admin-fotos@example.com", role="admin")
    user.set_password("segredo123")
    db.session.add(user)
    db.session.commit()
    return user


def _produto():
    produto = Product(
        name="Produto Sem Foto", price=10.0, stock=1, status="active"
    )
    db.session.add(produto)
    db.session.commit()
    return produto


def _envio(nome="foto.jpg"):
    # O formulário usa prefixo 'photo'; a rota decide pela presença de
    # 'photo-submit', não pelo valor.
    return {
        "photo-image": (io.BytesIO(b"conteudo-da-imagem"), nome),
        "photo-submit": "",
    }


def test_primeira_foto_vira_imagem_principal(app, client, monkeypatch):
    """Sem isso o topo fica em 'Imagem indisponível' mesmo com foto enviada."""

    user = _admin()
    produto = _produto()
    _login(monkeypatch, user)
    monkeypatch.setattr(app_module, "upload_to_s3", lambda *a, **k: "http://img/1.jpg")

    response = client.post(
        f"/produto/{produto.id}",
        data=_envio(),
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    produto = db.session.get(Product, produto.id)
    assert produto.image_url == "http://img/1.jpg"
    # A principal não deve também virar miniatura na galeria.
    assert ProductPhoto.query.filter_by(product_id=produto.id).count() == 0


def test_segunda_foto_vira_galeria_e_repetida_nao_duplica(app, client, monkeypatch):
    user = _admin()
    produto = _produto()
    _login(monkeypatch, user)

    monkeypatch.setattr(app_module, "upload_to_s3", lambda *a, **k: "http://img/1.jpg")
    client.post(
        f"/produto/{produto.id}", data=_envio(), content_type="multipart/form-data"
    )

    monkeypatch.setattr(app_module, "upload_to_s3", lambda *a, **k: "http://img/2.jpg")
    client.post(
        f"/produto/{produto.id}", data=_envio("outra.jpg"), content_type="multipart/form-data"
    )

    produto = db.session.get(Product, produto.id)
    assert produto.image_url == "http://img/1.jpg"
    assert ProductPhoto.query.filter_by(product_id=produto.id).count() == 1

    # Reenviar a mesma imagem não pode criar uma segunda miniatura igual.
    client.post(
        f"/produto/{produto.id}", data=_envio("outra.jpg"), content_type="multipart/form-data"
    )
    assert ProductPhoto.query.filter_by(product_id=produto.id).count() == 1

    # Nem reenviar a que já é a principal.
    monkeypatch.setattr(app_module, "upload_to_s3", lambda *a, **k: "http://img/1.jpg")
    client.post(
        f"/produto/{produto.id}", data=_envio(), content_type="multipart/form-data"
    )
    assert ProductPhoto.query.filter_by(product_id=produto.id).count() == 1
