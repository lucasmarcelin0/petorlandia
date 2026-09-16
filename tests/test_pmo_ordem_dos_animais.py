"""O desfecho de campo pertence ao ANIMAL, nunca à posição na lista.

Em 16/09/2026 uma casa com muitos cães apareceu na tela do vacinador com os
animais embaralhados: bichos que ainda não tinham sido vacinados estavam como
"vacinado" e os que já tinham recebido a dose voltaram para "pendente".

A causa estava em ``persist_vacina_pmo_rows``: o sync casava a lista da planilha
com o banco pela POSIÇÃO. A ordem da célula de nomes, porém, não é estável — o
parser distribui os nomes por espécie, a IA de nomes pode devolvê-los em outra
ordem e o vacinador inclui animais em campo (o que reordena cães e gatos). Toda
vez que a ordem mudava, o nome andava e o ``status`` ficava parado na posição.

Estes testes travam o casamento por nome.
"""

from __future__ import annotations

from datetime import date

from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit
from services.vacina_pmo_service import persist_vacina_pmo_rows

PLANILHA = {"spreadsheet_id": "plan-ordem", "sheet_gid": "77", "sheet_title": "16/09/2026"}


def _linha(animais, *, dogs=None, cats=None, source_row=5):
    return {
        "sourceRow": source_row,
        "tutor": "Mariuza Ap. Honorio Alves",
        "address": "Alameda 10, 268, Jardim Benini",
        "phone1": "5516991110000",
        "phone2": "",
        "dogs": dogs if dogs is not None else sum(1 for a in animais if a[1] == "cao"),
        "cats": cats if cats is not None else sum(1 for a in animais if a[1] == "gato"),
        "animals": [{"name": nome, "species": especie} for nome, especie in animais],
        "note": "",
        "date": "2026-09-16",
        "shift": "Manha",
        "password": "PMOAAAAA",
    }


def _visita():
    return PmoVaccinationVisit.query.filter_by(
        sheet_gid=PLANILHA["sheet_gid"], source_row=5
    ).one()


def _status_por_nome():
    return {animal.name: animal.status for animal in _visita().animals}


def _nomes_em_ordem():
    return [animal.name for animal in _visita().animals]


def _marcar(nomes, status="vacinado"):
    for nome in nomes:
        animal = PmoVaccinationAnimal.query.join(PmoVaccinationVisit).filter(
            PmoVaccinationVisit.sheet_gid == PLANILHA["sheet_gid"],
            PmoVaccinationAnimal.name == nome,
        ).one()
        animal.status = status
    db.session.commit()


def test_sync_com_a_celula_reordenada_nao_troca_o_status_de_lugar(app):
    """O caso de 16/09: metade da casa vacinada e a célula volta em outra ordem."""
    originais = [
        ("Mayla", "cao"), ("Tobias", "cao"), ("Thomas", "cao"),
        ("Max", "cao"), ("Priscila", "cao"), ("Mag", "cao"),
        ("Cao 7", "cao"), ("Cao 8", "cao"), ("Cao 9", "cao"),
        ("Cao 10", "cao"), ("Cao 11", "cao"), ("Neguinho", "cao"),
    ]
    persist_vacina_pmo_rows([_linha(originais)], **PLANILHA)
    _marcar(["Mayla", "Tobias", "Thomas", "Max", "Priscila", "Mag"])

    # A releitura da planilha devolve os MESMOS animais em outra ordem.
    reordenados = originais[6:] + originais[:6]
    persist_vacina_pmo_rows([_linha(reordenados)], **PLANILHA)

    status = _status_por_nome()
    assert status["Mayla"] == "vacinado"
    assert status["Mag"] == "vacinado"
    assert status["Cao 7"] == "pendente"
    assert status["Neguinho"] == "pendente"
    assert len([v for v in status.values() if v == "vacinado"]) == 6
    # A lista na tela nao dança no meio da rota: a ordem que o vacinador ja
    # conhece continua valendo, mesmo com a celula voltando embaralhada.
    assert _nomes_em_ordem() == [nome for nome, _ in originais]


def test_sync_nao_troca_status_quando_a_ordem_muda_por_especie(app):
    """Incluir um gato em campo reordena a casa (cães primeiro) — sem efeito colateral."""
    persist_vacina_pmo_rows(
        [_linha([("Florzinha", "cao"), ("Duda", "gato"), ("Mimi", "gato")])],
        **PLANILHA,
    )
    _marcar(["Duda", "Mimi"])

    persist_vacina_pmo_rows(
        [_linha([("Duda", "gato"), ("Florzinha", "cao"), ("Mimi", "gato"), ("Nala", "gato")])],
        **PLANILHA,
    )

    assert _status_por_nome() == {
        "Duda": "vacinado",
        "Florzinha": "pendente",
        "Mimi": "vacinado",
        "Nala": "pendente",
    }
    # Cães antes de gatos, e dentro de cada espécie a ordem que já estava na
    # tela — é a ordem que a coluna J recebe e devolve no sync seguinte.
    assert _nomes_em_ordem() == ["Florzinha", "Duda", "Mimi", "Nala"]


def test_animal_vacinado_que_sumiu_da_celula_continua_na_visita(app):
    """Apagar levaria junto a dose registrada, a foto e a carteirinha do tutor."""
    persist_vacina_pmo_rows(
        [_linha([("Bidu", "cao"), ("Luque", "cao")])], **PLANILHA
    )
    _marcar(["Luque"])

    persist_vacina_pmo_rows([_linha([("Bidu", "cao")], dogs=1)], **PLANILHA)

    assert _status_por_nome() == {"Bidu": "pendente", "Luque": "vacinado"}
    assert _nomes_em_ordem() == ["Bidu", "Luque"], "o preservado vai para o fim da lista"


def test_animal_pendente_que_sumiu_da_celula_continua_sendo_removido(app):
    """Sem trabalho de campo, a planilha continua mandando na lista."""
    persist_vacina_pmo_rows(
        [_linha([("Bidu", "cao"), ("Luque", "cao")])], **PLANILHA
    )

    persist_vacina_pmo_rows([_linha([("Bidu", "cao")], dogs=1)], **PLANILHA)

    assert _nomes_em_ordem() == ["Bidu"]


def test_nome_generico_corrigido_na_planilha_mantem_o_registro(app):
    """"Cao 2" que virou "Neguinho" é o MESMO animal — a correção não cria outro."""
    persist_vacina_pmo_rows(
        [_linha([("Bidu", "cao"), ("Cao 2", "cao")])], **PLANILHA
    )
    ids_antes = {animal.id for animal in _visita().animals}

    persist_vacina_pmo_rows(
        [_linha([("Bidu", "cao"), ("Neguinho", "cao")])], **PLANILHA
    )

    assert _nomes_em_ordem() == ["Bidu", "Neguinho"]
    assert {animal.id for animal in _visita().animals} == ids_antes


def test_nome_novo_nao_rouba_o_registro_de_quem_ja_foi_vacinado(app):
    """Se o slot livre acabou, um nome novo nasce em vez de herdar uma dose."""
    persist_vacina_pmo_rows(
        [_linha([("Bidu", "cao"), ("Luque", "cao")])], **PLANILHA
    )
    _marcar(["Luque"])

    persist_vacina_pmo_rows(
        [_linha([("Bidu", "cao"), ("Rex", "cao")])], **PLANILHA
    )

    status = _status_por_nome()
    assert status["Rex"] == "pendente", "o nome novo não pode herdar a dose de Luque"
    assert status["Luque"] == "vacinado"


def test_a_ordem_para_de_mudar_a_cada_sync(app):
    """A coluna J escrita agora tem que voltar idêntica no sync seguinte.

    Sem isso a lista dança a cada 10 minutos na mão do vacinador: ele perde a
    referência de onde parou e re-vacina (ou pula) animal.
    """
    persist_vacina_pmo_rows(
        [_linha([("Nina", "gato"), ("Bidu", "cao"), ("Lola", "gato")])], **PLANILHA
    )
    primeira = _nomes_em_ordem()

    # O sync seguinte lê de volta exatamente o que foi escrito na planilha.
    for _ in range(3):
        persist_vacina_pmo_rows(
            [_linha([(nome, especie) for nome, especie in zip(
                primeira,
                [a.species for a in _visita().animals],
            )])],
            **PLANILHA,
        )
        assert _nomes_em_ordem() == primeira
