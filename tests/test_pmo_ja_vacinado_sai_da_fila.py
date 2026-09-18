"""Animal com dose válida do ano não volta para a fila do dia.

A antirrábica é anual e a mesma casa reaparece na planilha o tempo todo —
encaixe, remarcação, cadastro novo feito pelo tutor. Quando isso acontecia, o
animal que já tinha tomado a dose há poucos meses abria a lista como
``pendente``: aparecia na soma de doses previstas, na folha impressa e na
planilha como se nunca tivesse sido vacinado. Estes testes fixam o desfecho
automático e, principalmente, os casos em que ele NÃO pode acontecer.
"""

from __future__ import annotations

from datetime import date, timedelta

from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit
from services.vacina_pmo_service import (
    PMO_IMMUNITY_DAYS,
    PMO_STATUS_ALREADY_IMMUNE,
    _serialize_visit,
    build_previous_immunity_index,
    get_saved_vacina_pmo_rows,
    resolve_animals_already_immune,
)


def _visita(sheet_title, *, animais, row=2, tutor="Isabela da Silva Franks",
            phone1="5516981817686", especie="gato"):
    visita = PmoVaccinationVisit(
        spreadsheet_id="plan-1",
        sheet_gid="0",
        sheet_title=sheet_title,
        source_row=row,
        tutor_name=tutor,
        address="Avenida 16, 1934, Jardim Cidade Alta",
        phone1=phone1,
        dogs=0,
        cats=len(animais),
        password="PMOTESTE",
    )
    db.session.add(visita)
    db.session.flush()
    for posicao, (nome, status) in enumerate(animais, start=1):
        db.session.add(PmoVaccinationAnimal(
            visit=visita, position=posicao, name=nome, species=especie, status=status,
        ))
    db.session.flush()
    return visita


def _resolver(visita):
    imunidade = build_previous_immunity_index([visita])
    return resolve_animals_already_immune([visita], imunidade)


def test_dose_do_ano_fecha_o_animal_sem_gastar_vacina(app):
    _visita("16/09/2026", animais=[("Mussum", "vacinado")])
    hoje = _visita("17/09/2026", animais=[("Mussum", "pendente")], row=3)
    db.session.commit()

    assert _resolver(hoje) is True

    animal = hoje.animals[0]
    # "imunizado", nunca "vacinado": nenhuma dose saiu do frasco, então consumo
    # e cobertura da campanha continuam intocados.
    assert animal.status == PMO_STATUS_ALREADY_IMMUNE
    assert animal.immune_since == date(2026, 9, 16)
    assert animal.vaccinated_at is None
    # A casa inteira resolvida some da fila do dia.
    assert _serialize_visit(hoje)["status"] == "vacinado"


def test_o_painel_abre_com_a_lista_ja_resolvida(app):
    _visita("16/09/2026", animais=[("Duda", "vacinado"), ("Nala", "vacinado")])
    _visita("17/09/2026", row=3, animais=[("Duda", "pendente"), ("Raimundo", "pendente")])
    db.session.commit()

    linhas = get_saved_vacina_pmo_rows(sheet_gid="0", sheet_title="17/09/2026")["rows"]
    por_nome = {a["name"]: a["status"] for a in linhas[0]["animals"]}

    assert por_nome["Duda"] == PMO_STATUS_ALREADY_IMMUNE
    assert por_nome["Raimundo"] == "pendente"
    assert linhas[0]["status"] == "parcial"


def test_a_tela_mostra_as_duas_datas_do_animal_resolvido(app):
    _visita("16/09/2026", animais=[("Mimi", "vacinado")])
    hoje = _visita("17/09/2026", animais=[("Mimi", "pendente")], row=3)
    db.session.commit()
    _resolver(hoje)

    animal = _serialize_visit(hoje)["animals"][0]
    assert animal["immuneSinceLabel"] == "16/09/2026"
    assert animal["immuneUntilLabel"] == "16/09/2027"


def test_nome_apenas_parecido_continua_pendente(app):
    """"Lipe" e "Lupe" podem ser dois gatos: quem decide é o vacinador."""
    _visita("16/09/2026", animais=[("Lipe", "vacinado")])
    hoje = _visita("17/09/2026", animais=[("Lupe", "pendente")], row=3)
    db.session.commit()

    assert _resolver(hoje) is False
    assert hoje.animals[0].status == "pendente"


def test_dose_vencida_nao_fecha_nada(app):
    antiga = date(2026, 9, 17) - timedelta(days=PMO_IMMUNITY_DAYS + 1)
    _visita(antiga.strftime("%d/%m/%Y"), animais=[("Adia", "vacinado")])
    hoje = _visita("17/09/2026", animais=[("Adia", "pendente")], row=3)
    db.session.commit()

    assert _resolver(hoje) is False
    assert hoje.animals[0].status == "pendente"


def test_desfecho_ja_registrado_pelo_vacinador_nao_e_sobrescrito(app):
    """Ausente, recusou e remarcar são trabalho de campo — ficam como estão."""
    _visita("16/09/2026", animais=[("Adia", "vacinado"), ("Nala", "vacinado"),
                                   ("Mimi", "vacinado")])
    hoje = _visita("17/09/2026", row=3, animais=[
        ("Adia", "ausente"), ("Nala", "recusou"), ("Mimi", "remarcar"),
    ])
    db.session.commit()

    assert _resolver(hoje) is False
    assert [a.status for a in hoje.animals] == ["ausente", "recusou", "remarcar"]


def test_a_observacao_registra_o_motivo_para_quem_ler_depois(app):
    _visita("16/09/2026", animais=[("Dominguinha", "vacinado")])
    hoje = _visita("17/09/2026", animais=[("Dominguinha", "pendente")], row=3)
    db.session.commit()
    _resolver(hoje)

    assert "Dominguinha" in (hoje.note or "")
    assert "16/09/2026" in (hoje.note or "")


def test_rodar_de_novo_nao_duplica_nada(app):
    _visita("16/09/2026", animais=[("Mussum", "vacinado")])
    hoje = _visita("17/09/2026", animais=[("Mussum", "pendente")], row=3)
    db.session.commit()

    assert _resolver(hoje) is True
    nota = hoje.note
    assert _resolver(hoje) is False
    assert hoje.note == nota
