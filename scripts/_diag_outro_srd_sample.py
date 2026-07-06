from app import app
from models import db, Animal, Breed, Species

with app.app_context():
    outro_srd = Breed.query.filter_by(name="SRD (Sem Raça Definida)").join(Species).filter(Species.name == "Outro").first()
    animals = Animal.query.filter_by(breed_id=outro_srd.id).order_by(Animal.id).all()
    print(f"Total: {len(animals)}")
    for a in animals[:80]:
        print(
            f"id={a.id} name={a.name!r} sex={getattr(a, 'sex', None)} "
            f"date_of_birth={getattr(a, 'date_of_birth', None)} age={getattr(a, 'age', None)} "
            f"clinica_id={a.clinica_id} owner_id={a.user_id}"
        )
