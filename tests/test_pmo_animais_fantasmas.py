"""A campanha não deixa animais alheios na conta do tutor.

Em 05/11/2026 a tutora Alessandra, dona de um único cachorro (Fred), achou 11
animais na própria conta. A sincronização cria o ``Animal`` real assim que lê a
linha da planilha; com a aba desalinhada, a linha dela trouxe por alguns dias
os bichos da casa vizinha ("Luna, Lara, Katy", depois "Pretinha, Pitica"...).
Quando a linha voltava a dizer "Fred", o vínculo era desfeito, mas o cadastro
criado ficava na conta dela. Em produção eram ~1.570 cadastros assim em 250
contas.
"""

from __future__ import annotations

from datetime import date

import pytest

from extensions import db
from models import Animal, PmoVaccinationAnimal, PmoVaccinationVisit, User, Vacina
from services import vacina_pmo_service as servico
from services.vacina_pmo_service import (
    PMO_AUTO_ANIMAL_DESCRIPTION,
    _animal_reference_columns,
    cleanup_pmo_orphan_animals,
    persist_vacina_pmo_rows,
)


ALESSANDRA = {"tutor": "Alessandra Dantas De Morais", "phone1": "5516991610056",
              "address": "Rua 3, 2117, Jardim Recreio"}


def _sem_efeitos_externos(monkeypatch):
    monkeypatch.setattr(servico, "_pmo_geocode_address", lambda address: None)
    monkeypatch.setattr(servico, "_pmo_lookup_verified_coords", lambda address: None)


def _linha(nomes, *, source_row=5, casa=ALESSANDRA):
    return {
        "sourceRow": source_row, "tutor": casa["tutor"], "address": casa["address"],
        "phone1": casa["phone1"], "phone2": "", "dogs": len(nomes), "cats": 0,
        "animals": [{"name": nome, "species": "cao"} for nome in nomes],
        "note": "", "date": "", "shift": "", "password": "PMOAAAAA",
    }


def _sync(nomes, **kwargs):
    persist_vacina_pmo_rows(
        [_linha(nomes, **kwargs)],
        spreadsheet_id="plan-1", sheet_gid="9", sheet_title="04/11/2026",
    )


def _tutora():
    visita = PmoVaccinationVisit.query.filter_by(sheet_gid="9").first()
    return db.session.get(User, visita.tutor_user_id)


def _animais_da_tutora():
    tutora = _tutora()
    return sorted(
        animal.name
        for animal in Animal.query.filter_by(user_id=tutora.id)
        if animal.removido_em is None
    )


def test_linha_que_trouxe_os_bichos_da_vizinha_nao_deixa_rastro(app, monkeypatch):
    _sem_efeitos_externos(monkeypatch)
    with app.app_context():
        _sync(["Fred"])

        _sync(["Luna", "Lara", "Katy"])  # aba desalinhada: bichos da casa de cima
        assert _animais_da_tutora() == ["Katy", "Lara", "Luna"]

        _sync(["Fred"])  # alguém corrige a planilha

        assert _animais_da_tutora() == ["Fred"]
        assert Animal.query.count() == 1


def test_animal_com_historico_nunca_e_apagado(app, monkeypatch):
    """Vacina, consulta ou foto: o cadastro deixa de ser rascunho e fica."""
    _sem_efeitos_externos(monkeypatch)
    with app.app_context():
        _sync(["Fred", "Toddy"])
        por_nome = {a.name: a.animal_id for a in PmoVaccinationAnimal.query}
        db.session.add(Vacina(animal_id=por_nome["Toddy"], nome="Antirrábica",
                              aplicada=True, aplicada_em=date(2026, 11, 4)))
        db.session.get(Animal, por_nome["Fred"]).image = "https://exemplo/fred.jpg"
        db.session.commit()

        _sync(["Rex"])

        assert db.session.get(Animal, por_nome["Toddy"]) is not None
        assert db.session.get(Animal, por_nome["Fred"]) is not None
        assert "Rex" in _animais_da_tutora()


def test_cadastro_ainda_ligado_a_outra_visita_fica(app, monkeypatch):
    """O mesmo Fred aparece na aba do dia e na mestre; sair de uma não o apaga."""
    _sem_efeitos_externos(monkeypatch)
    with app.app_context():
        _sync(["Fred"])
        persist_vacina_pmo_rows(
            [_linha(["Fred"], source_row=323)],
            spreadsheet_id="plan-1", sheet_gid="0", sheet_title="Vacinação 2026",
        )
        ids = {a.animal_id for a in PmoVaccinationAnimal.query}
        assert len(ids) == 1

        _sync(["Bolt"])

        assert db.session.get(Animal, ids.pop()) is not None
        assert _animais_da_tutora() == ["Bolt", "Fred"]


def test_limpeza_apaga_so_os_fantasmas_ja_existentes(app, monkeypatch):
    _sem_efeitos_externos(monkeypatch)
    with app.app_context():
        _sync(["Fred"])
        tutora = _tutora()
        sem_visita = User(name="Sem Visita", email="sem-visita@petorlandia.local", role="adotante")
        sem_visita.set_password("x")
        db.session.add(sem_visita)
        db.session.flush()

        def _orfao(nome, user_id, **extra):
            animal = Animal(name=nome, user_id=user_id, description=PMO_AUTO_ANIMAL_DESCRIPTION,
                            status="ativo", modo="adotado", **extra)
            db.session.add(animal)
            db.session.flush()
            return animal.id

        fantasma = _orfao("Luna", tutora.id)
        removido = _orfao("Pitica", tutora.id, removido_em=servico.utcnow())
        com_foto = _orfao("Kiara", tutora.id, image="https://exemplo/kiara.jpg")
        com_carteirinha = _orfao("Mel", tutora.id, public_token="tok-mel")
        com_vacina = _orfao("Coca", tutora.id)
        db.session.add(Vacina(animal_id=com_vacina, nome="Antirrábica"))
        de_quem_nao_tem_visita = _orfao("Bidu", sem_visita.id)
        db.session.commit()

        previa = cleanup_pmo_orphan_animals(dry_run=True)
        assert previa["removidos"] == 1
        assert previa["preservados_sem_visita"] == 1
        assert db.session.get(Animal, fantasma) is not None

        resultado = cleanup_pmo_orphan_animals(dry_run=False, tutor_id=tutora.id)

        assert resultado["removidos"] == 1
        assert db.session.get(Animal, fantasma) is None
        assert db.session.get(Animal, removido) is not None
        for preservado in (com_foto, com_carteirinha, com_vacina, de_quem_nao_tem_visita):
            assert db.session.get(Animal, preservado) is not None
        assert _animais_da_tutora() == ["Coca", "Fred", "Kiara", "Mel"]


def test_toda_tabela_que_aponta_para_animal_conta_como_historico(app):
    """Tabela nova com animal_id entra sozinha; a lista não é mantida à mão."""
    with app.app_context():
        tabelas = {coluna.table.name for coluna in _animal_reference_columns()}
    assert {"consulta", "vacina", "animal_photo", "pmo_vaccination_animal",
            "appointment", "bloco_prescricao"} <= tabelas


@pytest.mark.parametrize("extra", [
    {"peso": 12.5}, {"microchip_number": "CHIP123"},
    {"date_of_birth": date(2020, 1, 1)}, {"age": "6 anos"},
    {"sex": "femea"}, {"neutered": True}, {"health_plan": "Plano A"},
    {"description": PMO_AUTO_ANIMAL_DESCRIPTION + " Observacao do tutor."},
    {"is_alive": False}, {"falecido_em": servico.utcnow()},
    {"status": "perdido"}, {"modo": "doacao"}, {"price": 50.0},
])
def test_sync_e_limpeza_preservam_dados_acrescentados_no_cadastro(app, monkeypatch, extra):
    _sem_efeitos_externos(monkeypatch)
    with app.app_context():
        _sync(["Fred"])
        animal = Animal.query.one()
        animal_id = animal.id
        for field, value in extra.items():
            setattr(animal, field, value)
        db.session.commit()

        _sync(["Rex"])
        assert db.session.get(Animal, animal_id) is not None
        cleanup_pmo_orphan_animals(dry_run=False)
        preserved = db.session.get(Animal, animal_id)
        assert preserved is not None
        for field, value in extra.items():
            if field != "falecido_em":  # SQLite normaliza a zona do timestamp
                assert getattr(preserved, field) == value
