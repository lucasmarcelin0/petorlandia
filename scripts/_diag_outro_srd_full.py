from app import app
from models import db, Animal, Breed, Species

with app.app_context():
    outro_srd = Breed.query.filter_by(name="SRD (Sem Raça Definida)").join(Species).filter(Species.name == "Outro").first()
    animals = Animal.query.filter_by(breed_id=outro_srd.id).order_by(Animal.id).all()
    print(f"Total: {len(animals)}")
    for a in animals:
        print(f"id={a.id}|name={a.name}|dob={a.date_of_birth}")
