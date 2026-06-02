"""Organize public veterinarian visibility for Orlandia.

Marks interns and test records so they do not appear in public scheduling lists.
Keeps the known production-ready professionals public.
"""

import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_factory import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models import Endereco, Veterinario  # noqa: E402


PUBLIC_ORLANDIA = {
    "maisse cividanes degiovani",
    "ana carolina scorsato",
    "lucas marcelino campos ferreira",
}
INTERN_NAME_PARTS = {"laisa", "laiane"}
ORLANDIA = "Orlândia"


def normalize(value):
    normalized = (value or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", normalized)


def vet_city(vet):
    endereco = getattr(vet.user, "endereco", None)
    return (endereco.cidade or "").strip() if endereco and endereco.cidade else ""


def ensure_orlandia_address(user):
    if user.endereco is None:
        user.endereco = Endereco(cidade=ORLANDIA, estado="SP")
        return True
    changed = False
    if normalize(user.endereco.cidade) != normalize(ORLANDIA):
        user.endereco.cidade = ORLANDIA
        changed = True
    if not user.endereco.estado:
        user.endereco.estado = "SP"
        changed = True
    return changed


def main():
    app = create_app()
    dry_run = os.getenv("DRY_RUN", "0").lower() in {"1", "true", "yes"}
    updates = []

    with app.app_context():
        vets = Veterinario.query.join(Veterinario.user).all()
        for vet in vets:
            name = vet.user.name or ""
            name_key = normalize(name)
            city_key = normalize(vet_city(vet))

            target_type = None
            target_visible = None

            if name_key in PUBLIC_ORLANDIA:
                if ensure_orlandia_address(vet.user):
                    updates.append((name, "cidade=Orlândia"))
                target_type = "profissional"
                target_visible = True
            elif any(part in name_key for part in INTERN_NAME_PARTS):
                target_type = "estagiario"
                target_visible = False
            elif city_key == normalize(ORLANDIA):
                target_type = "teste"
                target_visible = False

            if target_type is None:
                continue

            changed = False
            if vet.public_profile_type != target_type:
                vet.public_profile_type = target_type
                changed = True
            if vet.public_visible != target_visible:
                vet.public_visible = target_visible
                changed = True
            if changed:
                updates.append((name, f"{target_type}, visible={target_visible}"))

        if not dry_run:
            db.session.commit()
        else:
            db.session.rollback()

    print({"dry_run": dry_run, "updates": updates, "total": len(updates)})


if __name__ == "__main__":
    main()
