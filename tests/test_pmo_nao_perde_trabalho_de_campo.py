"""Travas contra perder trabalho de campo por causa da planilha.

Em 25/08/2026 duas linhas indevidas empurraram as casas para baixo. O sync
seguinte apagou visitas cujo ``source_row`` tinha mudado, e com elas foram
status de vacinação, links de carteirinha e vínculos com a foto do animal.
O erro que causou o deslocamento já foi corrigido; estes testes garantem que,
se algo parecido acontecer de novo, o estrago não chega aos dados de campo.
"""

from __future__ import annotations

from datetime import date

import pytest

from extensions import db
from models import Animal, PmoVaccinationAnimal, PmoVaccinationVisit, Species, User
from services import vacina_pmo_service as servico
from services.vacina_pmo_service import (
    PMO_DONE_STATUSES,
    _ensure_real_animal,
    _pmo_visit_has_field_record,
    persist_vacina_pmo_rows,
)


def _visita(source_row, tutor="Ana Beatriz", animais=(("Luque", "cao", "pendente"),)):
    visita = PmoVaccinationVisit(
        spreadsheet_id="plan-1", sheet_gid="9", sheet_title="25/08/2026",
        source_row=source_row, tutor_name=tutor, address="Rua 1, 10",
        phone1="5516991234567", dogs=1, cats=0, password="PMOTESTE",
        vaccine_date=date(2026, 8, 25),
    )
    db.session.add(visita)
    db.session.flush()
    for posicao, (nome, especie, status) in enumerate(animais, start=1):
        db.session.add(PmoVaccinationAnimal(
            visit=visita, position=posicao, name=nome, species=especie, status=status,
        ))
    db.session.flush()
    return visita


def _linha_planilha(source_row, tutor="Outra Pessoa"):
    return {
        "sourceRow": source_row, "tutor": tutor, "address": "Rua 9, 99",
        "phone1": "5516999998888", "phone2": "", "dogs": 1, "cats": 0,
        "animals": [{"name": "Bidu", "species": "cao"}],
        "note": "", "date": "2026-08-25", "shift": "Manhã", "password": "PMOAAAAA",
    }


# --------------------------------------------------------------------------
# Trava 1: a poda nao apaga quem tem trabalho de campo
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", list(PMO_DONE_STATUSES))
def test_visita_com_animal_atendido_sobrevive_a_poda(app, status):
    """Foi o que apagou Luis carlos, Jessica e Ana Beatriz."""
    protegida = _visita(19, animais=(("Luque", "cao", status),))
    db.session.commit()
    protegida_id = protegida.id
    token = protegida.public_token

    # A linha 19 sumiu da planilha; so a 21 voltou do sync.
    persist_vacina_pmo_rows(
        [_linha_planilha(21)],
        spreadsheet_id="plan-1", sheet_gid="9", sheet_title="25/08/2026",
        prune_orphans=True,
    )

    sobrevivente = db.session.get(PmoVaccinationVisit, protegida_id)
    assert sobrevivente is not None, f"visita com animal {status} foi apagada"
    assert sobrevivente.public_token == token, "a carteirinha do tutor continua valendo"
    assert sobrevivente.animals[0].status == status
    assert sobrevivente.source_row < 0, "sai da lista do dia, mas o registro fica"


def test_visita_sem_nada_de_campo_continua_sendo_podada(app):
    """A limpeza precisa continuar funcionando para linha realmente removida."""
    vazia = _visita(19, animais=(("Luque", "cao", "pendente"),))
    db.session.commit()
    vazia_id = vazia.id

    persist_vacina_pmo_rows(
        [_linha_planilha(21)],
        spreadsheet_id="plan-1", sheet_gid="9", sheet_title="25/08/2026",
        prune_orphans=True,
    )

    assert db.session.get(PmoVaccinationVisit, vazia_id) is None


def test_a_trava_reconhece_os_dois_desfechos_de_campo(app):
    assert _pmo_visit_has_field_record(_visita(2, animais=(("A", "cao", "vacinado"),)))
    assert _pmo_visit_has_field_record(_visita(3, animais=(("B", "cao", "imunizado"),)))
    assert not _pmo_visit_has_field_record(_visita(4, animais=(("C", "cao", "pendente"),)))
    assert not _pmo_visit_has_field_record(_visita(5, animais=(("D", "cao", "ausente"),)))


# --------------------------------------------------------------------------
# Trava 2: religar o animal nao pode trocar a foto de lugar
# --------------------------------------------------------------------------

@pytest.fixture()
def sem_criar_tutor(monkeypatch):
    """Isola a escolha do cadastro do animal da criação da conta do tutor."""
    monkeypatch.setattr(servico, "_ensure_tutor_account", lambda visit: None)


def _tutor_com_duplicatas(app):
    tutor = User(name="Ana Beatriz", email="ana-dup@example.com", phone="")
    tutor.set_password("PMOA1111")
    especie = Species(name="Cachorro")
    db.session.add_all([tutor, especie])
    db.session.flush()
    # Cadastro antigo, com a foto tirada em campo.
    antigo = Animal(name="Luque", user_id=tutor.id, species=especie, status="ativo",
                    image="https://s3/animals/luque.jpg")
    db.session.add(antigo)
    db.session.flush()
    # Duplicata vazia criada depois (digitação diferente, corrida com o sync).
    novo = Animal(name="luque", user_id=tutor.id, species=especie, status="ativo")
    db.session.add(novo)
    db.session.flush()
    return tutor, antigo, novo


def test_religacao_escolhe_o_cadastro_que_tem_a_foto(app, sem_criar_tutor):
    """Foi o que fez as fotos do Luque e do Simba "sumirem"."""
    tutor, com_foto, sem_foto = _tutor_com_duplicatas(app)
    visita = _visita(19, animais=(("Luque", "cao", "vacinado"),))
    visita.tutor_user_id = tutor.id
    pmo_animal = visita.animals[0]
    pmo_animal.animal_id = None
    db.session.flush()

    _ensure_real_animal(pmo_animal)
    db.session.flush()

    assert pmo_animal.animal_id == com_foto.id, (
        "religou no cadastro vazio: a foto sumiria da carteirinha"
    )
    assert pmo_animal.animal.image


def test_religacao_e_estavel_entre_chamadas(app, sem_criar_tutor):
    """Chamar de novo nao pode trocar o vinculo — senao a foto pisca."""
    tutor, com_foto, _ = _tutor_com_duplicatas(app)
    visita = _visita(19, animais=(("Luque", "cao", "vacinado"),))
    visita.tutor_user_id = tutor.id
    pmo_animal = visita.animals[0]
    db.session.flush()

    escolhas = set()
    for _ in range(3):
        pmo_animal.animal = None
        pmo_animal.animal_id = None
        db.session.flush()
        _ensure_real_animal(pmo_animal)
        db.session.flush()
        escolhas.add(pmo_animal.animal_id)

    assert escolhas == {com_foto.id}, f"vinculo instavel entre chamadas: {escolhas}"


def test_sem_duplicata_o_comportamento_nao_muda(app, sem_criar_tutor):
    tutor = User(name="Tutor Unico", email="unico@example.com", phone="")
    tutor.set_password("PMOA2222")
    especie = Species(name="Cachorro")
    db.session.add_all([tutor, especie])
    db.session.flush()
    unico = Animal(name="Bidu", user_id=tutor.id, species=especie, status="ativo")
    db.session.add(unico)
    db.session.flush()

    visita = _visita(2, animais=(("Bidu", "cao", "pendente"),))
    visita.tutor_user_id = tutor.id
    pmo_animal = visita.animals[0]
    pmo_animal.animal_id = None
    db.session.flush()

    _ensure_real_animal(pmo_animal)
    db.session.flush()
    assert pmo_animal.animal_id == unico.id
