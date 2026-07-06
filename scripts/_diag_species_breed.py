from app import app
from models import db, Animal, Species, Breed

with app.app_context():
    species_by_id = {s.id: s.name for s in Species.query.all()}
    breeds = {b.id: b for b in Breed.query.all()}

    mismatches = 0
    outro_species_id = next((sid for sid, name in species_by_id.items() if name == "Outro"), None)
    print("Outro species_id:", outro_species_id)

    animals = Animal.query.filter(Animal.breed_id.isnot(None)).all()
    for a in animals:
        breed = breeds.get(a.breed_id)
        if breed is None:
            continue
        if a.species_id != breed.species_id:
            mismatches += 1
            print(
                f"animal id={a.id} name={a.name!r} "
                f"animal.species={species_by_id.get(a.species_id)} "
                f"breed.species={species_by_id.get(breed.species_id)} "
                f"breed.name={breed.name!r}"
            )

    print("total mismatches:", mismatches)

    if outro_species_id:
        count_animals_outro = Animal.query.filter_by(species_id=outro_species_id).count()
        print("animais com species_id=Outro:", count_animals_outro)
