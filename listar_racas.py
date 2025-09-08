from routes.app import app, db
from models import Species, Breed

novas_racas = [
    "Akita",
    "Basset Hound",
    "Beagle",
    "Border Collie",
    "Boxer",
    "Chihuahua",
    "Chow Chow",
    "Cocker Spaniel",
    "Doberman",
    "Fila Brasileiro",
    "Fox Paulistinha",
    "Husky Siberiano",
    "Lhasa Apso",
    "Maltês",
    "Pastor Belga",
    "Pit Bull",
    "Rottweiler",
    "São Bernardo",
    "Spitz Alemão (Lulu da Pomerânia)",
    "Weimaraner"
]

with app.app_context():
    especie = Species.query.filter(Species.name == 'Cachorro').first()
    if not especie:
        print("❌ Espécie 'Cachorro' não encontrada.")
    else:
        adicionadas = 0
        for nome_raca in novas_racas:
            existente = Breed.query.filter_by(name=nome_raca, species_id=especie.id).first()
            if not existente:
                nova_raca = Breed(name=nome_raca, species_id=especie.id)
                db.session.add(nova_raca)
                adicionadas += 1
        db.session.commit()
        print(f"✅ {adicionadas} novas raças adicionadas com sucesso.")
