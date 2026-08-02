from pathlib import Path

from extensions import db
from models import Product
from models.base import SiteFlag


def _product(**overrides):
    values = {
        "name": "Shampoo Clorexidina",
        "description": "Produto com embalagem vertical.",
        "price": 28,
        "stock": 4,
        "status": "active",
        "is_demo": False,
        "image_url": "https://cdn.example.test/products/shampoo.png",
    }
    values.update(overrides)
    product = Product(**values)
    db.session.add(product)
    db.session.commit()
    return product


def test_store_and_detail_share_the_canonical_product_media(app, client):
    product = _product()
    SiteFlag.set("loja_em_breve", False)
    db.session.commit()

    store_response = client.get("/loja")
    store_body = store_response.data.decode()
    detail_response = client.get(f"/produto/{product.id}")
    detail_body = detail_response.data.decode()

    assert store_response.status_code == 200
    assert detail_response.status_code == 200
    assert "product-media--card" in store_body
    assert "product-media--hero" in detail_body
    assert 'fetchpriority="high"' in detail_body
    assert 'src="https://cdn.example.test/products/shampoo.png"' in store_body
    assert 'src="https://cdn.example.test/products/shampoo.png"' in detail_body
    assert "object-fit:cover" not in detail_body


def test_product_media_supports_legacy_paths_and_missing_images(app):
    template = app.jinja_env.get_template("components/product_media.html")
    render = template.module.media_image

    legacy = render("static/uploads/products/item.png", "Item", "thumb")
    missing = render(None, "Sem foto", "card")

    assert 'src="/static/uploads/products/item.png"' in legacy
    assert "product-media--thumb" in legacy
    assert "product-media--empty" in missing
    assert "Imagem indisponível" in missing


def test_product_media_css_never_crops_catalog_photos(app):
    css = (Path(app.root_path) / "static" / "images.css").read_text(encoding="utf-8")
    component = css[css.index(".product-media {") : css.index(".profile-card-media")]

    assert "object-fit: contain" in component
    assert "object-position: center" in component
    assert "object-fit: cover" not in component
