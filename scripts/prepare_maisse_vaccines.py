"""Create or update Maisse's paid vaccine catalog in the active database."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import Clinica, User, VaccineServiceItem, Veterinario  # noqa: E402


VACCINES = [
    {
        "nome": "V8",
        "fabricante": "MSD Saúde Animal",
        "preco": Decimal("70.00"),
        "valor_repasse": Decimal("60.00"),
        "descricao": "Vacina múltipla canina V8 com aplicação em domicílio.",
        "doses_info": "Esquema e reforço definidos pela médica-veterinária.",
        "position": 10,
    },
    {
        "nome": "Raiva",
        "fabricante": "Virbac",
        "preco": Decimal("35.00"),
        "valor_repasse": Decimal("30.00"),
        "descricao": "Vacina contra a raiva com aplicação em domicílio.",
        "doses_info": "Dose e reforço conforme avaliação da médica-veterinária.",
        "position": 20,
    },
    {
        "nome": "V10",
        "fabricante": "Zoetis",
        "preco": Decimal("90.00"),
        "valor_repasse": Decimal("80.00"),
        "descricao": "Vacina múltipla canina V10 com aplicação em domicílio.",
        "doses_info": "Esquema e reforço definidos pela médica-veterinária.",
        "position": 30,
    },
]


def prepare() -> tuple[Clinica, Veterinario, list[VaccineServiceItem]]:
    email = "maissecividanes@hotmail.com"
    cnpj_digits = "63921336000107"

    owner = User.query.filter(db.func.lower(User.email) == email).first()
    clinics = Clinica.query.all()
    clinic = next(
        (
            candidate
            for candidate in clinics
            if "".join(filter(str.isdigit, candidate.cnpj or "")) == cnpj_digits
        ),
        None,
    )
    if clinic is None and owner is not None:
        clinic = Clinica.query.filter_by(owner_id=owner.id).first()
    if clinic is None:
        raise RuntimeError("Clínica da Maisse não encontrada.")

    if owner is None:
        owner = clinic.owner
    vet = Veterinario.query.filter_by(user_id=owner.id).first()
    if vet is None:
        vet = Veterinario.query.filter_by(clinica_id=clinic.id).first()
    if vet is None:
        raise RuntimeError("Cadastro veterinário da Maisse não encontrado.")

    items = []
    for payload in VACCINES:
        item = VaccineServiceItem.query.filter(
            db.func.lower(VaccineServiceItem.nome) == payload["nome"].lower(),
        ).first()
        if item is None:
            item = VaccineServiceItem(nome=payload["nome"])
            db.session.add(item)
        for field, value in payload.items():
            setattr(item, field, value)
        item.especies = "cao"
        item.provider_vet_id = vet.id
        item.ativo = True
        items.append(item)

    db.session.commit()
    return clinic, vet, items


def main() -> None:
    with app.app_context():
        clinic, vet, items = prepare()
        print(f"Clínica: {clinic.id} - {clinic.nome}")
        print(f"Veterinária: {vet.id} - {vet.user.name} - CRMV {vet.crmv}")
        for item in items:
            print(
                f"{item.id}: {item.nome} / {item.fabricante} / "
                f"tutor R$ {item.preco} / repasse R$ {item.valor_repasse}"
            )


if __name__ == "__main__":
    main()
