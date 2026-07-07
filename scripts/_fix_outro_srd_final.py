from app import app
from models import db, Animal, Breed, Species

# Confirmados como gatos via cruzamento nome+idade com o VetSmart real (lista
# de espécie "Felino" da clínica). Os demais animais do bucket "Outro/SRD"
# ficam como cachorro por eliminação (só 3 animais no total da clínica são
# Ave/Equino, nenhum deles com esses nomes).
CAT_IDS = {2229, 2252, 2279, 2281}

with app.app_context():
    cachorro = Species.query.filter_by(name="Cachorro").first()
    gato = Species.query.filter_by(name="Gato").first()
    outro = Species.query.filter_by(name="Outro").first()

    def get_or_create_srd(species):
        breed = Breed.query.filter(
            Breed.species_id == species.id, Breed.name.ilike("%SRD%")
        ).first()
        if breed is None:
            breed = Breed(name="SRD (Sem Raça Definida)", species_id=species.id)
            db.session.add(breed)
            db.session.flush()
        return breed

    cachorro_srd = get_or_create_srd(cachorro)
    gato_srd = get_or_create_srd(gato)

    # Só mexe nos animais "Outro" cuja raça é alguma variante de SRD (o lote
    # de importação com espécie vazia). Animais "Outro" com raça de verdade
    # (ex.: coelho, ave) ficam intocados.
    outro_srd_breed_ids = [
        b.id for b in Breed.query.filter(
            Breed.species_id == outro.id, Breed.name.ilike("%SRD%")
        ).all()
    ]
    animals = (
        Animal.query.filter(
            Animal.species_id == outro.id,
            Animal.breed_id.in_(outro_srd_breed_ids),
        ).order_by(Animal.id).all()
        if outro_srd_breed_ids else []
    )
    print(f"Total a reclassificar: {len(animals)}")

    for a in animals:
        if a.id in CAT_IDS:
            a.species_id = gato.id
            a.breed_id = gato_srd.id
            print(f"  #{a.id} {a.name!r} -> Gato/SRD")
        else:
            a.species_id = cachorro.id
            a.breed_id = cachorro_srd.id
            print(f"  #{a.id} {a.name!r} -> Cachorro/SRD")

    db.session.commit()
    print("Concluido.")
