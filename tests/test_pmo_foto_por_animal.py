# -*- coding: utf-8 -*-
"""Cada bicho da visita tem o seu proprio cadastro real.

Bug de campo (03/09/2026, Avenida 9): a foto tirada da Luna aparecia tambem na
Mia e continuava la depois de recarregar. As duas linhas da visita apontavam
para o mesmo ``Animal`` -- ``_ensure_real_animal`` escolhia o cadastro pelo
nome do tutor sem olhar para os irmaos da mesma visita, e a planilha traz nomes
repetidos ate o vacinador renomear na tela.

O mesmo vinculo compartilhado fazia a dose de um bicho ser deduplicada na do
outro em ``_ensure_pmo_vaccine_record``, que casa por ``animal_id`` + data.
"""

from __future__ import annotations

from datetime import date

import pytest

from extensions import db
from models import Animal, PmoVaccinationAnimal, PmoVaccinationVisit, User, Vacina
from services.vacina_pmo_service import (
    _ensure_real_animal,
    _ensure_tutor_account,
    repair_pmo_duplicate_animal_links,
)


def _visit(**overrides) -> PmoVaccinationVisit:
    defaults = dict(
        spreadsheet_id="sheet-1",
        sheet_gid="0",
        sheet_title="03/09/2026",
        source_row=2,
        tutor_name="Marina Prado",
        address="Avenida 9, 358, A, Centro",
        phone1="16999990001",
        dogs=2,
        cats=0,
        password="PMOABCDE",
        vaccine_date=date(2026, 9, 3),
    )
    defaults.update(overrides)
    visit = PmoVaccinationVisit(**defaults)
    db.session.add(visit)
    db.session.flush()
    # A conta do tutor ja existe quando a tela chama o vinculo; criar aqui
    # mantem o teste no assunto (o vinculo bicho<->cadastro) e independente do
    # momento do flush que popula ``tutor_user_id``.
    _ensure_tutor_account(visit)
    db.session.flush()
    return visit


def _pmo_animal(visit, name, position, status="pendente") -> PmoVaccinationAnimal:
    animal = PmoVaccinationAnimal(
        visit_id=visit.id,
        position=position,
        name=name,
        species="cachorro",
        status=status,
    )
    db.session.add(animal)
    db.session.flush()
    return animal


def test_nomes_repetidos_na_visita_nao_dividem_o_mesmo_cadastro(app):
    """Duas linhas 'Luna' na mesma visita sao dois bichos, nao um."""
    visit = _visit()
    primeira = _pmo_animal(visit, "Luna", 1)
    segunda = _pmo_animal(visit, "Luna", 2)

    _ensure_real_animal(primeira)
    db.session.flush()
    _ensure_real_animal(segunda)
    db.session.flush()

    assert primeira.animal_id is not None
    assert segunda.animal_id is not None
    assert primeira.animal_id != segunda.animal_id


def test_foto_de_um_nao_aparece_no_outro(app):
    """O sintoma que o vacinador viu na tela."""
    visit = _visit()
    luna = _pmo_animal(visit, "Luna", 1)
    mia = _pmo_animal(visit, "Luna", 2)
    _ensure_real_animal(luna)
    db.session.flush()
    _ensure_real_animal(mia)
    db.session.flush()

    db.session.get(Animal, luna.animal_id).image = "https://s3/luna.jpg"
    db.session.flush()

    assert db.session.get(Animal, mia.animal_id).image is None


def test_cadastro_de_campanha_anterior_continua_sendo_reaproveitado(app):
    """Nao pode virar 'um cadastro novo por campanha': o historico se perderia."""
    antiga = _visit(sheet_title="11/08/2026", source_row=2)
    ano_passado = _pmo_animal(antiga, "Luna", 1)
    _ensure_real_animal(ano_passado)
    db.session.flush()
    cadastro_original = ano_passado.animal_id
    assert cadastro_original is not None

    nova = _visit(sheet_title="03/09/2026", source_row=7)
    deste_ano = _pmo_animal(nova, "Luna", 1)
    _ensure_real_animal(deste_ano)
    db.session.flush()

    assert deste_ano.animal_id == cadastro_original


def test_reparo_separa_vinculo_ja_duplicado_e_recria_a_dose(app):
    """Dados que ja estao no banco com o vinculo trocado."""
    visit = _visit()
    luna = _pmo_animal(visit, "Luna", 1, status="vacinado")
    mia = _pmo_animal(visit, "Mia", 2, status="vacinado")

    _ensure_real_animal(luna)
    db.session.flush()
    compartilhado = luna.animal_id
    # Reproduz o estado defeituoso: a Mia foi renomeada depois de ja ter sido
    # vinculada ao cadastro da Luna.
    mia.animal_id = compartilhado
    db.session.get(Animal, compartilhado).image = "https://s3/luna.jpg"
    db.session.flush()

    previa = repair_pmo_duplicate_animal_links(dry_run=True)
    assert previa["animais_separados"] == 1
    assert mia.animal_id == compartilhado, "dry_run nao pode gravar nada"

    resultado = repair_pmo_duplicate_animal_links(dry_run=False)
    assert resultado["animais_separados"] == 1

    assert luna.animal_id == compartilhado, "quem tem o nome do cadastro fica com ele"
    assert mia.animal_id is not None
    assert mia.animal_id != compartilhado
    assert db.session.get(Animal, mia.animal_id).name == "Mia"
    # A foto pertence a um bicho so: nao e copiada para o cadastro novo.
    assert db.session.get(Animal, mia.animal_id).image is None
    # E a dose que estava deduplicada na Luna agora existe para a Mia.
    assert Vacina.query.filter_by(animal_id=mia.animal_id, aplicada=True).count() == 1
