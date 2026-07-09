import importlib

from extensions import db
from models import Breed, Species


def test_list_breeds_deduplicates_srd_aliases(app):
    app_module = importlib.import_module("app")

    with app.app_context():
        dog = Species(name="Cachorro")
        cat = Species(name="Gato")
        db.session.add_all([dog, cat])
        db.session.flush()
        db.session.add_all([
            Breed(name="SRD", species_id=dog.id),
            Breed(name="SRD (Sem Raça Definida)", species_id=cat.id),
            Breed(name="Sem raça definida", species_id=dog.id),
            Breed(name="Pit Bull", species_id=dog.id),
            Breed(name="Bull Terrier", species_id=dog.id),
        ])
        db.session.commit()

        app_module.list_breeds.cache_clear()
        breeds = app_module.list_breeds()

    names = [breed["name"] for breed in breeds]
    assert names.count("SRD") == 1
    assert "Pit Bull" in names
    assert "Bull Terrier" in names
