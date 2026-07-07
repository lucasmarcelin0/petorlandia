from app import app
from models import db, Breed, Species, Animal

with app.app_context():
    print("=== Racas com 'bull' ou 'terrier' ===")
    for b in Breed.query.filter(Breed.name.ilike("%bull%") | Breed.name.ilike("%terrier%")).all():
        count = Animal.query.filter_by(breed_id=b.id).count()
        print(f"  #{b.id} species={b.species.name} name={b.name!r} animais={count}")

    print("\n=== Racas com 'SRD' ===")
    for b in Breed.query.filter(Breed.name.ilike("%SRD%")).all():
        count = Animal.query.filter_by(breed_id=b.id).count()
        print(f"  #{b.id} species={b.species.name} name={b.name!r} animais={count}")

    print(f"\nTotal de racas no banco: {Breed.query.count()}")
