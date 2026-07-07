import re
import unicodedata
from collections import defaultdict

from app import app
from models import db, Breed, Animal


def norm(name):
    raw = (name or "").strip()
    n = unicodedata.normalize("NFKD", raw)
    n = "".join(ch for ch in n if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", n).strip().lower()


with app.app_context():
    breeds = Breed.query.order_by(Breed.species_id, Breed.name).all()
    groups = defaultdict(list)
    for b in breeds:
        groups[(b.species_id, norm(b.name))].append(b)

    print("=== Possiveis duplicatas exatas (mesma especie, nome normalizado igual) ===")
    for (sp_id, key), rows in groups.items():
        if len(rows) > 1:
            for b in rows:
                count = Animal.query.filter_by(breed_id=b.id).count()
                print(f"  #{b.id} species_id={sp_id} name={b.name!r} animais={count}")

    print("\n=== Possiveis quase-duplicatas (nomes parecidos, especies diferentes) ===")
    by_norm_only = defaultdict(list)
    for b in breeds:
        by_norm_only[norm(b.name)].append(b)
    for key, rows in by_norm_only.items():
        species_ids = {b.species_id for b in rows}
        if len(rows) > 1 and len(species_ids) > 1 and key != "srd":
            for b in rows:
                count = Animal.query.filter_by(breed_id=b.id).count()
                print(f"  #{b.id} species_id={b.species_id} name={b.name!r} animais={count}")

    print("\n=== Racas com 0 animais (candidatas a limpeza, so informativo) ===")
    empty = [b for b in breeds if Animal.query.filter_by(breed_id=b.id).count() == 0]
    print(f"  Total: {len(empty)} de {len(breeds)}")
