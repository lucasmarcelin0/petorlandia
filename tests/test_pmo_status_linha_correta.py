"""O "Status PMO" só pode ser gravado na linha do tutor a que ele pertence.

A aba mestre é reordenada e reescrita pela equipe (o menu da planilha limpa e
regrava a aba inteira ordenada por cluster) e linhas incompletas não voltam do
parser. Quando a posição guardada no banco envelhece, escrever pelo número da
linha carimba o status de um tutor no cadastro de outro — foi como um "Vacinado
em 20/08" apareceu no cadastro de quem nunca foi atendido.

Estes testes fixam o contrato da correção: conferir quem está na linha antes de
escrever, realinhar quando o tutor apenas mudou de lugar, limpar a nota que
ficou no cadastro errado e não perder nada do comportamento anterior.
"""

from __future__ import annotations

import pytest

from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit
from scripts.sync_pmo_master_status_notes import (
    MASTER_SHEET_TITLE,
    STATUS_LINK_COLUMN_INDEX,
    TIMESTAMP_COLUMN_INDEX,
    _build_requests,
    _build_visit_index,
    _matching_visits,
    _master_row_identities,
    _name_texts_compatible,
    _row_identity,
)


MASTER_SHEET_ID = 777


def _visit(**overrides) -> PmoVaccinationVisit:
    defaults = dict(
        spreadsheet_id="sheet-1",
        sheet_gid="0",
        sheet_title=MASTER_SHEET_TITLE,
        source_row=224,
        tutor_name="Raquel Feliciano",
        address="Rua 4, 1299, A, Jardim Siena",
        phone1="16992510438",
        phone2="16991443152",
        dogs=1,
        cats=0,
        password="PMOABCDE",
    )
    defaults.update(overrides)
    visit = PmoVaccinationVisit(**defaults)
    db.session.add(visit)
    db.session.flush()
    return visit


def _animal(visit: PmoVaccinationVisit, name: str, status: str) -> PmoVaccinationAnimal:
    animal = PmoVaccinationAnimal(
        visit=visit, position=1, name=name, species="cao", status=status
    )
    db.session.add(animal)
    db.session.flush()
    return animal


def _identity(name: str, *, phone: str = "", note_tutor: str = "") -> dict:
    """Linha da planilha como ``_row_identity`` a devolve."""
    row = [{"formattedValue": "17/08/2026 14:42:13"}, {"formattedValue": name}]
    row += [{"formattedValue": ""} for _ in range(4)]
    row.append({"formattedValue": phone})
    if note_tutor:
        row[0]["note"] = f"PetOrlandia PMO\nTutor: {note_tutor}\nStatus geral: Vacinado"
    return _row_identity(row)


def _note_rows(requests: list[dict]) -> dict[int, str]:
    """Linha (1-based) -> texto da nota gravada na coluna A."""
    found = {}
    for request in requests:
        cell = request.get("repeatCell", {})
        note = cell.get("cell", {}).get("note")
        column = cell.get("range", {}).get("startColumnIndex")
        if note and column == TIMESTAMP_COLUMN_INDEX:
            found[cell["range"]["startRowIndex"] + 1] = note
    return found


def _status_rows(requests: list[dict]) -> dict[int, str]:
    """Linha (1-based) -> texto gravado na coluna M."""
    found = {}
    for request in requests:
        cell = request.get("repeatCell", {})
        range_ = cell.get("range", {})
        if range_.get("startColumnIndex") != STATUS_LINK_COLUMN_INDEX:
            continue
        if range_.get("startRowIndex", 0) < 1:
            continue  # cabeçalho
        value = cell.get("cell", {}).get("userEnteredValue", {}).get("stringValue")
        if value is not None:
            found[range_["startRowIndex"] + 1] = value
    return found


def _matches_for(master: PmoVaccinationVisit, other: PmoVaccinationVisit) -> dict:
    return {master.id: [other]}


# ---------------------------------------------------------------------------
# Conferência da linha antes de escrever
# ---------------------------------------------------------------------------

def test_nao_grava_status_na_linha_de_outro_tutor(app):
    """Posição velha no banco: a linha é de outra pessoa, então não se escreve."""
    master = _visit(tutor_name="Iraneide Maria de Sousa", phone1="16988887777", phone2="")
    campo = _visit(
        sheet_title="20/08/2026",
        sheet_gid="9",
        source_row=2,
        tutor_name="Iraneide Maria de Sousa",
        phone1="16988887777",
        phone2="",
    )
    _animal(campo, "Ted", "vacinado")

    identities = {224: _identity("Raquel Feliciano", phone="16992510438")}
    requests = _build_requests(
        MASTER_SHEET_ID, [master], _matches_for(master, campo), row_identities=identities
    )

    assert _note_rows(requests) == {}
    assert _status_rows(requests) == {}


def test_realinha_quando_o_tutor_mudou_de_linha(app):
    """A aba foi reordenada: escreve na linha onde o tutor está agora."""
    master = _visit(tutor_name="Iraneide Maria de Sousa", phone1="16988887777", phone2="")
    campo = _visit(
        sheet_title="20/08/2026",
        sheet_gid="9",
        source_row=2,
        tutor_name="Iraneide Maria de Sousa",
        phone1="16988887777",
        phone2="",
    )
    _animal(campo, "Ted", "vacinado")

    identities = {
        224: _identity("Raquel Feliciano", phone="16992510438"),
        243: _identity("Iraneide Maria de Sousa", phone="16988887777"),
    }
    requests = _build_requests(
        MASTER_SHEET_ID, [master], _matches_for(master, campo), row_identities=identities
    )

    notes = _note_rows(requests)
    assert list(notes) == [243]
    assert "Iraneide" in notes[243]
    assert _status_rows(requests)[243].startswith("Vacinado")


def test_escreve_normalmente_quando_a_linha_confere(app):
    master = _visit()
    campo = _visit(
        sheet_title="20/08/2026", sheet_gid="9", source_row=2, tutor_name="Raquel Feliciano"
    )
    _animal(campo, "Pipoca", "vacinado")

    identities = {224: _identity("Raquel Feliciano", phone="16992510438")}
    requests = _build_requests(
        MASTER_SHEET_ID, [master], _matches_for(master, campo), row_identities=identities
    )

    assert "Raquel Feliciano" in _note_rows(requests)[224]
    assert _status_rows(requests)[224].startswith("Vacinado")


def test_sem_conferencia_mantem_o_comportamento_antigo(app):
    """Falha ao reler a planilha não pode parar a sincronização."""
    master = _visit()
    campo = _visit(
        sheet_title="20/08/2026", sheet_gid="9", source_row=2, tutor_name="Raquel Feliciano"
    )
    _animal(campo, "Pipoca", "vacinado")

    requests = _build_requests(
        MASTER_SHEET_ID, [master], _matches_for(master, campo), row_identities=None
    )

    assert 224 in _note_rows(requests)


def test_linha_sem_correspondencia_continua_preservada(app):
    """Sem match não se escreve nada — e nada do que já estava lá se perde."""
    master = _visit()
    identities = {224: _identity("Raquel Feliciano", phone="16992510438")}

    requests = _build_requests(
        MASTER_SHEET_ID, [master], {master.id: []}, row_identities=identities
    )

    assert _note_rows(requests) == {}
    assert _status_rows(requests) == {}


# ---------------------------------------------------------------------------
# Limpeza da nota que ficou no cadastro errado
# ---------------------------------------------------------------------------

def test_limpa_nota_de_outro_tutor(app):
    """A nota de Iraneide parada na linha de Raquel é apagada."""
    master = _visit()
    identities = {
        224: _identity(
            "Raquel Feliciano", phone="16992510438", note_tutor="Iraneide Maria de Sousa"
        )
    }

    requests = _build_requests(
        MASTER_SHEET_ID, [master], {master.id: []}, row_identities=identities
    )

    assert _note_rows(requests) == {}  # nota nova nenhuma
    limpezas = [
        r for r in requests
        if r.get("repeatCell", {}).get("cell", {}).get("note") == ""
        and r["repeatCell"]["range"]["startRowIndex"] == 223
    ]
    assert limpezas, "a nota do tutor errado precisa ser apagada"
    assert _status_rows(requests)[224] == ""


def test_nao_limpa_a_nota_do_proprio_tutor(app):
    master = _visit()
    identities = {
        224: _identity("Raquel Feliciano", phone="16992510438", note_tutor="Raquel Feliciano")
    }

    requests = _build_requests(
        MASTER_SHEET_ID, [master], {master.id: []}, row_identities=identities
    )

    assert not [
        r for r in requests if r.get("repeatCell", {}).get("cell", {}).get("note") == ""
    ]


def test_nota_nova_substitui_a_antiga_sem_limpeza_extra(app):
    """Quando a linha vai receber status novo, não se emite limpeza para ela."""
    master = _visit()
    campo = _visit(
        sheet_title="20/08/2026", sheet_gid="9", source_row=2, tutor_name="Raquel Feliciano"
    )
    _animal(campo, "Pipoca", "vacinado")
    identities = {
        224: _identity(
            "Raquel Feliciano", phone="16992510438", note_tutor="Iraneide Maria de Sousa"
        )
    }

    requests = _build_requests(
        MASTER_SHEET_ID, [master], _matches_for(master, campo), row_identities=identities
    )

    assert "Raquel Feliciano" in _note_rows(requests)[224]
    assert not [
        r for r in requests if r.get("repeatCell", {}).get("cell", {}).get("note") == ""
    ]


# ---------------------------------------------------------------------------
# Identidade: nome e vínculo de conta
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "left, right, compativel",
    [
        ("Raquel Feliciano", "Raquel Feliciano", True),
        ("Maria Silva", "Maria de Souza Silva", True),
        ("Maria", "Maria Aparecida", True),
        # Substring crua unia tutores diferentes: "ana lima" cabe em "joana lima".
        ("Ana Lima", "Joana Lima", False),
        ("Maria", "Ana Maria Costa", False),
        ("Raquel Feliciano", "Iraneide Maria de Sousa", False),
    ],
)
def test_nomes_compativeis(left, right, compativel):
    assert _name_texts_compatible(left, right) is compativel


def test_conta_compartilhada_nao_basta_para_casar_visitas(app):
    """Vínculo de conta errado (sync antigo) não pode importar status de outra casa."""
    master = _visit(tutor_name="Raquel Feliciano", tutor_user_id=42)
    outra_casa = _visit(
        sheet_title="20/08/2026",
        sheet_gid="9",
        source_row=2,
        tutor_name="Iraneide Maria de Sousa",
        phone1="16988887777",
        phone2="",
        tutor_user_id=42,
    )
    _animal(outra_casa, "Ted", "vacinado")

    by_phone, by_name, by_user = _build_visit_index([master, outra_casa])
    matches = _matching_visits(master, by_phone=by_phone, by_name=by_name, by_user=by_user)

    assert matches == []


def test_conta_compartilhada_com_mesmo_telefone_continua_casando(app):
    """A mesma casa em duas abas segue casando pelo vínculo de conta."""
    master = _visit(tutor_name="Raquel F.", tutor_user_id=42)
    mesma_casa = _visit(
        sheet_title="20/08/2026",
        sheet_gid="9",
        source_row=2,
        tutor_name="Raquel Feliciano da Silva",
        tutor_user_id=42,
    )
    _animal(mesma_casa, "Pipoca", "vacinado")

    by_phone, by_name, by_user = _build_visit_index([master, mesma_casa])
    matches = _matching_visits(master, by_phone=by_phone, by_name=by_name, by_user=by_user)

    assert matches == [mesma_casa]


# ---------------------------------------------------------------------------
# Leitura da planilha
# ---------------------------------------------------------------------------

class _FakeSheets:
    def __init__(self, rows):
        self._rows = rows

    def spreadsheets(self):
        return self

    def get(self, **kwargs):
        self.kwargs = kwargs
        return self

    def execute(self):
        return {"sheets": [{"data": [{"rowData": self._rows}]}]}


def _grid_row(*cells) -> dict:
    return {"values": [{"formattedValue": value} for value in cells]}


def test_le_nome_e_telefone_da_linha_com_carimbo_de_data_e_hora():
    """O formulário grava data E hora na coluna A; o nome está na B."""
    service = _FakeSheets([
        _grid_row("Carimbo", "Tutor", "Rua"),
        _grid_row(
            "17/08/2026 14:42:13", "Raquel Feliciano", "Rua 4", "1299", "A",
            "Jardim Siena", "16992510438", "16991443152",
        ),
    ])

    identities = _master_row_identities(service, "sheet-1")

    assert list(identities) == [2]
    assert identities[2]["name"] == "Raquel Feliciano"
    assert "16992510438" in identities[2]["phone_keys"]


def test_ignora_o_cabecalho_e_linhas_vazias():
    service = _FakeSheets([
        _grid_row("Carimbo", "Tutor"),
        _grid_row("", ""),
        _grid_row("17/08/2026", "Iraneide Maria de Sousa"),
    ])

    assert list(_master_row_identities(service, "sheet-1")) == [3]
