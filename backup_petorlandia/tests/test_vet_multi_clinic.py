import os
import sys
import pytest

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db
from models import User, Veterinario, Clinica


@pytest.fixture
def app_context():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.session.remove()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def test_veterinario_pode_participar_de_multiplas_clinicas(app_context):
    user = User(name="Vet", email="vet@example.com", password_hash="x", worker="veterinario")
    vet = Veterinario(user=user, crmv="123")
    c1 = Clinica(nome="Clinica 1")
    c2 = Clinica(nome="Clinica 2")
    vet.clinicas.extend([c1, c2])
    db.session.add_all([user, vet, c1, c2])
    db.session.commit()

    assert {c.nome for c in vet.clinicas} == {"Clinica 1", "Clinica 2"}
    assert vet in c1.veterinarios_associados
    assert vet in c2.veterinarios_associados
