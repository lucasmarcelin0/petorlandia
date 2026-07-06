from app import app
from models import db, Breed, Species, Animal

with app.app_context():
    print("=== Raças com 'bull' ou 'terrier' no nome ===")
    rows = Breed.query.filter(Breed.name.ilike("%bull%") | Breed.name.ilike("%terrier%")).all()
    for b in rows:
        count = Animal.query.filter_by(breed_id=b.id).count()
        print(f"  #{b.id} species={b.species.name} name={b.name!r} animais={count}")

    print("\n=== Raças com 'SRD' no nome ===")
    rows = Breed.query.filter(Breed.name.ilike("%SRD%")).all()
    for b in rows:
        count = Animal.query.filter_by(breed_id=b.id).count()
        print(f"  #{b.id} species={b.species.name} name={b.name!r} animais={count}")
