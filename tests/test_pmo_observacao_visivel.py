"""Observação da planilha visível para quem está na rua.

A coluna K carrega o que o morador combinou ("só depois das 17h", "portão do
fundo") misturado com o log de status que o próprio sistema empilha. Na tela do
vacinador o texto saía inteiro num bloco pequeno no rodapé do card — no
celular ele ainda era cortado em duas linhas —, então a hora combinada ficava
escondida bem quando ela decide a ordem da rota.
"""

from __future__ import annotations

from datetime import date

import pytest

from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit, User
from services.vacina_pmo_service import (
    _serialize_visit,
    extract_pmo_note_highlights,
    extract_pmo_schedule_hint,
)


def _visita(note, tutor="Maria de Jesus", row=1):
    visita = PmoVaccinationVisit(
        spreadsheet_id="plan-1", sheet_gid="9", sheet_title="11/08/2026",
        shift="Manha", source_row=row, tutor_name=tutor,
        address="Rua 14, 394, Centro", phone1="5516988078555", dogs=0, cats=1,
        password="PMO%04d" % row, note=note, vaccine_date=date(2026, 8, 11),
    )
    db.session.add(visita)
    db.session.flush()
    db.session.add(PmoVaccinationAnimal(
        visit=visita, position=1, name="Oliver", species="gato", status="pendente"))
    db.session.flush()
    return visita


# --- Leitura do texto ------------------------------------------------------

def test_destaque_descarta_o_log_de_status():
    note = "So depois das 17h | 17:17 - Fred: vacinado. | 15:40 - Um gatinho morreu"
    assert extract_pmo_note_highlights(note) == [
        "So depois das 17h",
        "Um gatinho morreu",
    ]


@pytest.mark.parametrize("texto, esperado", [
    ("So pode as 14h", "14h"),
    ("Atender depois das 17h", "a partir de 17h"),
    ("Chegar antes das 9:30, ela trabalha", "ate 9h30"),
    ("Tutora pede horario entre 8h e 9h30", "8h as 9h30"),
    ("das 8 as 11h", "8h as 11h"),
    ("atender 7h30", "7h30"),
    ("Precisa ser 14:00", "14h"),
])
def test_horario_combinado_sai_do_texto_livre(texto, esperado):
    hint = extract_pmo_schedule_hint(texto)
    assert hint is not None
    # Comparação sem acento: o rótulo mostra "às"/"até" para o vacinador.
    normalizado = hint["label"].replace("às", "as").replace("até", "ate")
    assert normalizado == esperado


@pytest.mark.parametrize("texto", [
    "Casa com 2 caes bravos",
    "Remarcar a partir de 22/07/2026",
    "Telefone 16982116928",
    "portao do fundo",
    "3 caes e 1 gato",
    "Rua 15 de novembro, 250",
    "17:17 - Fred: vacinado.",
    "",
])
def test_texto_sem_hora_nao_inventa_horario(texto):
    """Número solto (animais, data, telefone) não pode virar horário."""
    assert extract_pmo_schedule_hint(texto) is None


def test_horario_ignora_o_carimbo_do_proprio_log():
    """"17:17 - " é o relógio do sistema, não a hora combinada com o tutor."""
    assert extract_pmo_schedule_hint("17:17 - Levar coleira") is None


def test_minutos_permitem_ordenar_os_horarios_do_dia():
    manha = extract_pmo_schedule_hint("as 8h30")
    tarde = extract_pmo_schedule_hint("as 14h")
    assert manha["minutes"] == 510
    assert tarde["minutes"] == 840


# --- Payload da tela -------------------------------------------------------

def test_visita_leva_observacao_e_horario_para_a_tela(app):
    visita = _visita("Vacinar so depois das 17h | 17:17 - Oliver: pendente.")
    db.session.commit()

    payload = _serialize_visit(visita)

    assert payload["noteHighlights"] == ["Vacinar so depois das 17h"]
    assert payload["scheduleHint"]["label"] == "a partir de 17h"
    # O texto cru continua inteiro: o histórico não se perde no rodapé do card.
    assert payload["note"] == visita.note


def test_visita_sem_observacao_nao_ganha_destaque(app):
    visita = _visita("17:17 - Oliver: pendente.", tutor="Sem obs", row=2)
    db.session.commit()

    payload = _serialize_visit(visita)

    assert payload["noteHighlights"] == []
    assert payload["scheduleHint"] is None


# --- Folha impressa --------------------------------------------------------

def _login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_folha_impressa_avisa_as_casas_com_hora_marcada(app):
    client = app.test_client()

    admin = User(name="PMO Admin", email="pmo-obs-print@test", role="admin")
    admin.set_password("x")
    db.session.add(admin)
    _visita("Passar depois das 17h, ela trabalha", tutor="Maria de Jesus", row=1)
    _visita("Portao do fundo", tutor="Joao Silva", row=2)
    db.session.commit()
    _login(client, admin.id)

    body = client.get("/vacina-pmo/imprimir/11-08-2026/manha").get_data(as_text=True)

    assert "1 casa(s) com horário combinado" in body
    assert "Maria de Jesus" in body
    assert 'class="hora">a partir de 17h<' in body
    # A casa sem hora continua com a observação, só não entra no aviso do topo.
    assert "Portao do fundo" in body


def test_folha_impressa_sem_horario_nao_mostra_o_aviso(app):
    client = app.test_client()

    admin = User(name="PMO Admin", email="pmo-obs-print-vazio@test", role="admin")
    admin.set_password("x")
    db.session.add(admin)
    _visita("Portao do fundo", tutor="Joao Silva", row=1)
    db.session.commit()
    _login(client, admin.id)

    body = client.get("/vacina-pmo/imprimir/11-08-2026/manha").get_data(as_text=True)

    assert "casa(s) com horário combinado" not in body


# --- Tela do vacinador -----------------------------------------------------

def test_dashboard_monta_o_destaque_da_observacao(app):
    client = app.test_client()

    admin = User(name="PMO Admin", email="pmo-obs-dash@test", role="admin")
    admin.set_password("x")
    db.session.add(admin)
    db.session.commit()
    _login(client, admin.id)

    body = client.get("/vacina-pmo").get_data(as_text=True)

    # Destaque no card/tabela e o resumo dos horários acima da lista.
    assert "renderNoteHighlight" in body
    assert 'id="pmo-schedule-banner"' in body
    assert "renderScheduleBanner(visible)" in body
