# -*- coding: utf-8 -*-
"""Desfaz "ja imunizado" que veio de outra casa.

Até a correção de 01/10/2026, quando a linha da planilha passava para outro
tutor, o registro era reaproveitado e os animais renomeados mantinham o status
``imunizado`` e o ``immune_since`` do animal anterior. Daí a data falsa ainda
se espalhava: o desfecho automático usava essa "dose" para fechar como
imunizado o mesmo animal em outras listas.

Um ``imunizado`` só se sustenta se:
  - a observação da visita registra o desfecho para esse animal (marcado à mão
    pelo vacinador, com a data da carteirinha), ou
  - existe, em outra visita da mesma casa, o mesmo animal (mesmo cadastro,
    mesmo nome ou nome com uma letra de diferença, sem conflito de espécie)
    vacinado ou já imunizado de forma sustentada.

A sustentação é calculada a partir dos vacinados, em ponto fixo, para que dois
registros contaminados da mesma casa não se sustentem um ao outro. O que sobra
volta para ``pendente``; se houver dose real, o painel volta a fechar sozinho.

Sem flags roda em SIMULAÇÃO. Use --apply para gravar.

    python scripts/repair_pmo_imunizado_herdado.py
    python scripts/repair_pmo_imunizado_herdado.py --apply
"""

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import joinedload

from app import app
from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit
from services.vacina_pmo_service import (
    PMO_STATUS_ALREADY_IMMUNE,
    _pmo_address_slug,
    _pmo_animal_slug,
    _pmo_close_slugs,
    _pmo_same_household,
    _pmo_species_match,
    _pmo_visit_phones,
    _strip_accents,
)


def _note_records(visit, animal) -> bool:
    note = _strip_accents(visit.note or "").casefold()
    name = _strip_accents(animal.name or "").casefold().strip()
    return bool(name) and f"{name}: ja imunizado" in note


def _same_animal(left, right) -> bool:
    if left.animal_id and left.animal_id == right.animal_id:
        return True
    if _pmo_species_match(left.species, right.species) == "conflito":
        return False
    a, b = _pmo_animal_slug(left.name), _pmo_animal_slug(right.name)
    return bool(a) and (a == b or _pmo_close_slugs(a, b))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with app.app_context():
        visits = (
            PmoVaccinationVisit.query.options(joinedload(PmoVaccinationVisit.animals)).all()
        )
        by_key = defaultdict(set)
        for visit in visits:
            for phone in _pmo_visit_phones(visit):
                by_key[("fone", phone)].add(visit)
            slug = _pmo_address_slug(visit.address)
            if slug:
                by_key[("end", slug)].add(visit)

        def neighbours(visit):
            keys = [("fone", p) for p in _pmo_visit_phones(visit)]
            slug = _pmo_address_slug(visit.address)
            if slug:
                keys.append(("end", slug))
            found = set()
            for key in keys:
                found |= by_key.get(key, set())
            found.discard(visit)
            return [other for other in found if _pmo_same_household(visit, other)]

        grounded: set[int] = set()
        pending: list[tuple] = []
        for visit in visits:
            for animal in visit.animals:
                if animal.status == "vacinado":
                    grounded.add(animal.id)
                elif animal.status == PMO_STATUS_ALREADY_IMMUNE:
                    if _note_records(visit, animal):
                        grounded.add(animal.id)
                    else:
                        pending.append((visit, animal, neighbours(visit)))

        changed = True
        while changed:
            changed = False
            still = []
            for visit, animal, households in pending:
                if any(
                    other_animal.id in grounded and _same_animal(animal, other_animal)
                    for other in households
                    for other_animal in other.animals
                ):
                    grounded.add(animal.id)
                    changed = True
                else:
                    still.append((visit, animal, households))
            pending = still

        print(f"imunizado sem sustentação: {len(pending)}")
        for visit, animal, _ in sorted(pending, key=lambda item: (item[0].id, item[1].position)):
            print(
                f"  visita {visit.id} [{visit.sheet_title}] {visit.tutor_name!r} "
                f"-> {animal.name} ({animal.species}) dose {animal.immune_since}"
            )
            if args.apply:
                animal.status = "pendente"
                animal.immune_since = None
        if args.apply:
            db.session.commit()
            print("gravado.")
        else:
            print("simulação: nada gravado (use --apply).")


if __name__ == "__main__":
    main()
