"""Mesclagem de duas contas que sao a mesma pessoa.

O caso real: a mesma tutora cadastrada duas vezes, com telefones e e-mails
diferentes (uma delas veio da importacao do VetSmart), cada uma com seus
animais. Juntar as duas nao pode deixar registro orfao -- ha 104 chaves
estrangeiras apontando para user.id, e por isso o script descobre as colunas do
metadata em vez de manter uma lista escrita a mao.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from extensions import db
from models import Animal, MedicamentoFavorito, User

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _tutor(name: str, email: str, **overrides) -> User:
    user = User(name=name, email=email, **overrides)
    user.set_password("senha")
    db.session.add(user)
    db.session.flush()
    return user


@pytest.fixture
def merge():
    from scripts.merge_tutor_accounts import merge_accounts

    return merge_accounts


def test_merge_moves_animals_to_the_surviving_account(app, merge):
    with app.app_context():
        origem = _tutor("Leticia Mara Pereira", "leticia@example.com", phone="16991103219")
        destino = _tutor("Leticia Maira Pereira", "tutor_9dd@vetsmart.import", phone="16994427044")
        db.session.add_all([
            Animal(name="Spike", user_id=origem.id),
            Animal(name="Bob", user_id=destino.id),
        ])
        db.session.commit()
        origem_id, destino_id = origem.id, destino.id

        assert merge(source_id=origem_id, target_id=destino_id) == 0

        assert Animal.query.filter_by(user_id=origem_id).count() == 0
        nomes = {a.name for a in Animal.query.filter_by(user_id=destino_id)}
        assert nomes == {"Spike", "Bob"}


def test_merge_inherits_fields_the_survivor_lacks(app, merge):
    with app.app_context():
        origem = _tutor("Leticia A", "a@example.com", cpf="34963950871", phone="16991103219")
        destino = _tutor("Leticia B", "b@example.com")
        db.session.commit()
        origem_id, destino_id = origem.id, destino.id

        merge(source_id=origem_id, target_id=destino_id)

        destino = db.session.get(User, destino_id)
        assert destino.cpf == "34963950871"
        assert destino.phone == "16991103219"
        # E fica registrado de onde veio.
        assert f"#{origem_id}" in destino.observacoes


def test_merge_does_not_overwrite_fields_the_survivor_already_has(app, merge):
    with app.app_context():
        origem = _tutor("Leticia A", "a@example.com", phone="16991103219")
        destino = _tutor("Leticia B", "b@example.com", phone="16994427044")
        db.session.commit()
        origem_id, destino_id = origem.id, destino.id

        merge(source_id=origem_id, target_id=destino_id)

        assert db.session.get(User, destino_id).phone == "16994427044"


def test_dry_run_changes_nothing(app, merge):
    with app.app_context():
        origem = _tutor("Leticia A", "a@example.com")
        destino = _tutor("Leticia B", "b@example.com")
        db.session.add(Animal(name="Spike", user_id=origem.id))
        db.session.commit()
        origem_id, destino_id = origem.id, destino.id

        assert merge(source_id=origem_id, target_id=destino_id, dry_run=True) == 0

        assert Animal.query.filter_by(user_id=origem_id).count() == 1
        assert db.session.get(User, destino_id).observacoes is None


def test_source_survives_unless_delete_is_requested(app, merge):
    with app.app_context():
        origem = _tutor("Leticia A", "a@example.com")
        destino = _tutor("Leticia B", "b@example.com")
        db.session.commit()
        origem_id, destino_id = origem.id, destino.id

        merge(source_id=origem_id, target_id=destino_id)

        origem = db.session.get(User, origem_id)
        assert origem is not None
        assert f"#{destino_id}" in origem.observacoes

        merge(source_id=origem_id, target_id=destino_id, delete_source=True)

        assert db.session.get(User, origem_id) is None


def test_merge_refuses_same_account(app, merge):
    with app.app_context():
        tutor = _tutor("Leticia", "a@example.com")
        db.session.commit()

        assert merge(source_id=tutor.id, target_id=tutor.id) != 0


def test_merge_drops_rows_that_would_violate_a_unique_constraint(app, merge):
    """medicamento_favorito tem unique(user_id, medicamento_id)."""
    from models import Medicamento

    with app.app_context():
        origem = _tutor("Leticia A", "a@example.com")
        destino = _tutor("Leticia B", "b@example.com")
        medicamento = Medicamento(nome="Dipirona", created_by=origem.id)
        db.session.add(medicamento)
        db.session.flush()
        db.session.add_all([
            MedicamentoFavorito(user_id=origem.id, medicamento_id=medicamento.id),
            MedicamentoFavorito(user_id=destino.id, medicamento_id=medicamento.id),
        ])
        db.session.commit()
        origem_id, destino_id = origem.id, destino.id

        assert merge(source_id=origem_id, target_id=destino_id) == 0

        assert MedicamentoFavorito.query.filter_by(user_id=origem_id).count() == 0
        assert MedicamentoFavorito.query.filter_by(user_id=destino_id).count() == 1
