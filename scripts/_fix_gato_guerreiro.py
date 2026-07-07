from app import app
from models import db, Animal, Species, Breed

with app.app_context():
    gato = Species.query.filter_by(name="Gato").first()
    gato_srd = Breed.query.filter(Breed.species_id == gato.id, Breed.name.ilike("%SRD%")).first()

    a = Animal.query.get(2215)
    print(f"Antes: #{a.id} {a.name!r} species_id={a.species_id} breed_id={a.breed_id}")
    a.species_id = gato.id
    a.breed_id = gato_srd.id
    db.session.commit()
    print(f"Depois: #{a.id} {a.name!r} species_id={a.species_id} breed_id={a.breed_id}")
