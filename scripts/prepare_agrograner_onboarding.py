"""Prepare AgroGraner data and print Sabrina's private onboarding link."""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import app, normalize_phone  # noqa: E402
from extensions import db  # noqa: E402
from models import CasaDeRacao, CasaDeRacaoOnboardingInvite, Product, User  # noqa: E402


PRODUCTS = [
    ("Simparic", "simparic.png", "medicamento"),
    ("Shampoo de Clorexidina World 500 mL", "shampoo-clorexidina-world.png", "higiene"),
    ("Dermotrat Creme", "dermotrat-creme.png", "medicamento"),
    ("Canex Original", "canex-original.webp", "medicamento"),
    ("Organew Pet", "organew-pet.png", "medicamento"),
    ("Eletrolítico Pet", "eletrolitico-pet.webp", "medicamento"),
    ("Glicopan Gold", "glicopan-gold.webp", "medicamento"),
    ("Hemolipet", "hemolipet.webp", "medicamento"),
    ("Agemoxi CL", "agemoxi-cl.jpg", "medicamento"),
    ("Hemolitan Gold", "hemolitan-gold.webp", "medicamento"),
    ("Cerenia", "cerenia.png", "medicamento"),
    ("Panolog", "panolog.png", "medicamento"),
]


def _find_owner(phone: str) -> User | None:
    normalized = normalize_phone(phone)
    for user in User.query.filter(User.phone.isnot(None)).all():
        if normalize_phone(user.phone) == normalized:
            return user
    return None


def prepare(base_url: str, validity_days: int) -> str:
    phone = "+553492013165"
    owner = _find_owner(phone)
    if owner is None:
        owner = User(
            name="Sabrina Agrograner",
            email=f"agrograner.{secrets.token_hex(5)}@convite.petorlandia.local",
            phone=phone,
        )
        owner.set_password(secrets.token_urlsafe(32))
        db.session.add(owner)
        db.session.flush()

    casa = CasaDeRacao.query.filter_by(owner_id=owner.id).first()
    if casa is None:
        casa = CasaDeRacao(
            nome="AgroGraner",
            telefone=phone,
            owner_id=owner.id,
            status="pendente",
            modo_entrega="plataforma",
            valor_frete=0,
        )
        db.session.add(casa)
        db.session.flush()

    casa.nome = casa.nome or "AgroGraner"
    casa.telefone = casa.telefone or phone
    casa.logotipo = "uploads/casas_de_racao/agrograner/logo.png"

    image_root = PROJECT_ROOT / "static" / "uploads" / "casas_de_racao" / "agrograner" / "products"
    for name, filename, category in PRODUCTS:
        image_file = image_root / filename
        if not image_file.exists():
            raise FileNotFoundError(f"Imagem ausente para {name}: {image_file}")
        product = Product.query.filter_by(casa_de_racao_id=casa.id, name=name).first()
        if product is None:
            product = Product(
                casa_de_racao_id=casa.id,
                name=name,
                description="Apresentação a confirmar com a loja.",
                price=0,
                stock=0,
                status="inactive",
            )
            db.session.add(product)
        product.image_url = f"uploads/casas_de_racao/agrograner/products/{filename}"
        product.category = category
        product.mp_category_id = "pet_supplies"
        if product.price <= 0:
            product.status = "inactive"

    now = datetime.now(timezone.utc)
    CasaDeRacaoOnboardingInvite.query.filter_by(
        casa_de_racao_id=casa.id,
        used_at=None,
    ).update({"used_at": now})

    raw_token = secrets.token_urlsafe(32)
    invite = CasaDeRacaoOnboardingInvite(
        casa_de_racao_id=casa.id,
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        expires_at=now + timedelta(days=validity_days),
    )
    db.session.add(invite)
    db.session.commit()

    return f"{base_url.rstrip('/')}/ativar-loja/{raw_token}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=os.environ.get("FRONTEND_URL", "http://127.0.0.1:5000"),
        help="Public PetOrlândia URL used in the generated link.",
    )
    parser.add_argument("--validity-days", type=int, default=7)
    args = parser.parse_args()

    with app.app_context():
        link = prepare(args.base_url, args.validity_days)

    print("Onboarding AgroGraner preparado.")
    print(link)


if __name__ == "__main__":
    main()
