"""Dose anterior visível para o vacinador em campo.

A antirrábica é anual. Quando a mesma casa volta para a lista — encaixe,
remarcação ou cadastro novo feito pelo próprio tutor — o vacinador chegava sem
saber que parte dos animais tinha tomado a dose há poucos meses. Estes testes
fixam as decisões que isso força: quando dois registros são o mesmo animal,
quando a dose ainda protege, e que o aviso nunca some no meio do atendimento.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit
from services.vacina_pmo_service import (
    PMO_DOSE_STATUSES,
    PMO_IMMUNITY_DAYS,
    PMO_STATUS_ALREADY_IMMUNE,
    _count_vaccinated_by_species,
    _serialize_visit,
    build_previous_immunity_index,
    infer_visit_status,
    update_vacina_pmo_animal_status,
)


def _visita(sheet_title, *, tutor="Isabela da Silva Franks", phone1="5516981817686",
            address="Avenida 16, 1934, Jardim Cidade Alta", animais=(), row=2,
            vaccine_date=None, phone2=None):
    visita = PmoVaccinationVisit(
        spreadsheet_id="plan-1",
        sheet_gid="0",
        sheet_title=sheet_title,
        source_row=row,
        tutor_name=tutor,
        address=address,
        phone1=phone1,
        phone2=phone2,
        dogs=len(animais),
        cats=0,
        vaccine_date=vaccine_date,
        password="PMOTESTE",
    )
    db.session.add(visita)
    db.session.flush()
    for posicao, (nome, status) in enumerate(animais, start=1):
        db.session.add(PmoVaccinationAnimal(
            visit=visita, position=posicao, name=nome, species="cao", status=status,
        ))
    db.session.flush()
    return visita


# --------------------------------------------------------------------------
# Reconhecer o mesmo animal
# --------------------------------------------------------------------------

def test_nome_igual_na_mesma_casa_marca_dose_anterior(app):
    _visita("20/01/2026", animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", animais=[("Mia", "pendente")], row=3)

    indice = build_previous_immunity_index([hoje])
    dose = indice[hoje.id][hoje.animals[0].id]

    assert dose["dateLabel"] == "20/01/2026"
    assert dose["match"] == "exato"
    assert dose["immune"] is True
    assert dose["protectedUntilLabel"] == "20/01/2027"


def test_uma_letra_de_diferenca_pede_conferencia_em_vez_de_afirmar(app):
    """"Lipe" numa lista e "Lupe" na seguinte é redigitação, não outro cão."""
    _visita("20/01/2026", animais=[("Lipe", "vacinado")])
    hoje = _visita("25/08/2026", animais=[("Lupe", "pendente")], row=3)

    dose = build_previous_immunity_index([hoje])[hoje.id][hoje.animals[0].id]

    assert dose["match"] == "aproximado"
    assert dose["matchedName"] == "Lipe"
    assert dose["immune"] is True


def test_nomes_curtos_parecidos_nao_sao_colapsados(app):
    """"Bob" e "Bib" podem ser dois cães da mesma casa."""
    _visita("20/01/2026", animais=[("Bob", "vacinado")])
    hoje = _visita("25/08/2026", animais=[("Bib", "pendente")], row=3)

    assert build_previous_immunity_index([hoje]) == {}


def test_animal_ligado_ao_cadastro_dispensa_o_nome(app):
    from models import Animal, Species, User

    tutor = User(name="Tutor Cadastro", email="tutor-cadastro@example.com", phone="")
    tutor.set_password("PMOA0001")
    especie = Species(name="Cachorro")
    db.session.add_all([tutor, especie])
    db.session.flush()
    animal = Animal(name="Chico", user_id=tutor.id, species=especie, status="ativo")
    db.session.add(animal)
    db.session.flush()

    antiga = _visita("20/01/2026", animais=[("Apelido antigo", "vacinado")])
    antiga.animals[0].animal_id = animal.id
    hoje = _visita("25/08/2026", animais=[("Chico", "pendente")], row=3)
    hoje.animals[0].animal_id = animal.id
    db.session.flush()

    dose = build_previous_immunity_index([hoje])[hoje.id][hoje.animals[0].id]
    assert dose["match"] == "cadastro"


# --------------------------------------------------------------------------
# Reconhecer a mesma casa
# --------------------------------------------------------------------------

def test_outro_tutor_no_mesmo_bairro_nao_herda_a_dose(app):
    _visita("20/01/2026", tutor="Outra Pessoa Qualquer", phone1="5516999990000",
            address="Rua 3, 20, Centro", animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", animais=[("Mia", "pendente")], row=3)

    assert build_previous_immunity_index([hoje]) == {}


def test_mesma_casa_reconhecida_pelo_telefone_secundario(app):
    _visita("20/01/2026", phone1="5516993402190", address="Endereco digitado de outro jeito",
            animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", phone1="5516981817686", phone2="5516993402190",
                   animais=[("Mia", "pendente")], row=3)

    assert build_previous_immunity_index([hoje])[hoje.id]


def test_mesmo_nome_e_endereco_bastam_quando_o_telefone_mudou(app):
    _visita("20/01/2026", phone1="5516900000000", animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", phone1="5516911111111",
                   animais=[("Mia", "pendente")], row=3)

    assert build_previous_immunity_index([hoje])[hoje.id]


# --------------------------------------------------------------------------
# Janela de proteção
# --------------------------------------------------------------------------

def test_dose_de_mais_de_um_ano_aparece_como_vencida(app):
    _visita("20/01/2026", vaccine_date=date(2024, 3, 12), animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente")], row=3)

    dose = build_previous_immunity_index([hoje])[hoje.id][hoje.animals[0].id]

    assert dose["immune"] is False
    assert dose["dateLabel"] == "12/03/2024"


def test_limite_de_um_ano(app):
    """No 364º dia ainda protege; no 365º já não."""
    aplicacao = date(2026, 8, 25) - timedelta(days=PMO_IMMUNITY_DAYS - 1)
    _visita("dose", vaccine_date=aplicacao, animais=[("Mia", "vacinado")])
    hoje = _visita("hoje", vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente")], row=3)
    assert build_previous_immunity_index([hoje])[hoje.id][hoje.animals[0].id]["immune"] is True

    db.session.query(PmoVaccinationVisit).filter_by(sheet_title="dose").one().vaccine_date = (
        date(2026, 8, 25) - timedelta(days=PMO_IMMUNITY_DAYS)
    )
    db.session.flush()
    assert build_previous_immunity_index([hoje])[hoje.id][hoje.animals[0].id]["immune"] is False


def test_dose_futura_nao_conta(app):
    """Lista de amanhã já cadastrada não pode "proteger" a visita de hoje."""
    _visita("futura", vaccine_date=date(2026, 9, 30), animais=[("Mia", "vacinado")])
    hoje = _visita("hoje", vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente")], row=3)

    assert build_previous_immunity_index([hoje]) == {}


def test_animal_apenas_ausente_nao_gera_protecao(app):
    _visita("20/01/2026", animais=[("Mia", "ausente")])
    hoje = _visita("25/08/2026", animais=[("Mia", "pendente")], row=3)

    assert build_previous_immunity_index([hoje]) == {}


def test_dose_mais_recente_vence_quando_ha_varias(app):
    _visita("10/02/2025", vaccine_date=date(2025, 2, 10), animais=[("Mia", "vacinado")])
    _visita("20/01/2026", vaccine_date=date(2026, 1, 20), animais=[("Mia", "vacinado")], row=4)
    hoje = _visita("25/08/2026", vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente")], row=3)

    dose = build_previous_immunity_index([hoje])[hoje.id][hoje.animals[0].id]
    assert dose["dateLabel"] == "20/01/2026"


def test_data_do_animal_tem_prioridade_sobre_a_data_da_visita(app):
    antiga = _visita("20/01/2026", vaccine_date=date(2026, 1, 20),
                     animais=[("Mia", "vacinado")])
    antiga.animals[0].vaccinated_at = datetime(2026, 1, 22, 10, 30)
    db.session.flush()
    hoje = _visita("25/08/2026", vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente")], row=3)

    dose = build_previous_immunity_index([hoje])[hoje.id][hoje.animals[0].id]
    assert dose["dateLabel"] == "22/01/2026"


# --------------------------------------------------------------------------
# O aviso chega até a tela
# --------------------------------------------------------------------------

def test_serializacao_leva_o_aviso_para_a_tela(app):
    _visita("20/01/2026", animais=[("Lipe", "vacinado"), ("Mia", "vacinado")])
    hoje = _visita("25/08/2026", row=3, animais=[
        ("Lupe", "pendente"), ("Mia", "pendente"), ("Chico", "pendente"),
    ])
    db.session.commit()

    payload = _serialize_visit(hoje)
    por_nome = {a["name"]: a["previousVaccination"] for a in payload["animals"]}

    assert por_nome["Mia"]["match"] == "exato"
    assert por_nome["Lupe"]["match"] == "aproximado"
    assert por_nome["Chico"] is None, "animal novo não pode ganhar aviso"


def test_aviso_sobrevive_a_mudanca_de_status_no_meio_do_atendimento(app):
    """A rota de status devolve a visita sozinha; sem cálculo próprio o aviso sumiria."""
    _visita("20/01/2026", animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", row=3, animais=[("Mia", "pendente"), ("Chico", "pendente")])
    db.session.commit()

    hoje.animals[1].status = "vacinado"
    db.session.commit()

    payload = _serialize_visit(hoje)
    por_nome = {a["name"]: a["previousVaccination"] for a in payload["animals"]}
    assert por_nome["Mia"]["immune"] is True


def test_casa_sem_historico_nao_paga_nada_no_payload(app):
    hoje = _visita("25/08/2026", animais=[("Chico", "pendente")])
    db.session.commit()

    payload = _serialize_visit(hoje)
    assert payload["animals"][0]["previousVaccination"] is None


# --------------------------------------------------------------------------
# A folha impressa que vai a campo
# --------------------------------------------------------------------------

def test_folha_impressa_marca_o_animal_ja_protegido(app):
    from blueprints.vacina_pmo import _build_pmo_print_rows

    _visita("20/01/2026", vaccine_date=date(2026, 1, 20),
            animais=[("Lipe", "vacinado"), ("Mia", "vacinado")])
    hoje = _visita("25/08/2026", row=3, vaccine_date=date(2026, 8, 25), animais=[
        ("Lupe", "pendente"), ("Mia", "pendente"), ("Chico", "pendente"),
    ])
    db.session.commit()

    linhas = _build_pmo_print_rows([hoje], "25/08/2026")
    protegidos = linhas[0]["protegidos"]
    por_nome = {a.name: protegidos.get(a.id) for a in hoje.animals}

    assert por_nome["Mia"]["dateLabel"] == "20/01/2026"
    assert por_nome["Lupe"]["match"] == "aproximado"
    assert por_nome["Chico"] is None

    from flask import render_template

    with app.test_request_context("/vacina-pmo/imprimir/25-08-2026/manha"):
        html = render_template(
            "vacina_pmo/imprimir.html",
            visits=[hoje], rows=linhas,
            totals={"casas": 1, "caes": 3, "gatos": 0, "animais": 3,
                    "densidade": "normal", "paginas": 1},
            sheet_title="25/08/2026", shift_label="Manhã", shift_key="Manha",
            date_str="25-08-2026", other_turno="tarde",
        )

    assert "já vacinado em 20/01/2026" in html
    assert "conferir" in html, "o nome aproximado precisa pedir conferência no papel"


# --------------------------------------------------------------------------
# "Não precisou de dose": desfecho sem consumir vacina
# --------------------------------------------------------------------------

def _marcar_imunizado(app, monkeypatch, animal_id):
    """Aplica o status pela função real, com a planilha desligada."""
    from services import vacina_pmo_service as servico

    for nome in ("write_vaccinated_counts_to_sheet", "write_note_to_sheet",
                 "write_tutor_name_color_to_sheet", "write_attended_by_to_sheet"):
        monkeypatch.setattr(servico, nome, lambda *a, **k: False)
    with app.test_request_context():
        return update_vacina_pmo_animal_status(animal_id, PMO_STATUS_ALREADY_IMMUNE)


def test_imunizado_nao_conta_dose_nem_carimba_aplicacao(app, monkeypatch):
    _visita("20/01/2026", vaccine_date=date(2026, 1, 20), animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", row=3, vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente"), ("Chico", "pendente")])
    db.session.commit()

    _marcar_imunizado(app, monkeypatch, hoje.animals[0].id)
    db.session.refresh(hoje)
    mia = hoje.animals[0]

    assert mia.status == PMO_STATUS_ALREADY_IMMUNE
    assert mia.vaccinated_at is None, "sem dose aplicada, sem carimbo de aplicação"
    assert mia.immune_since == date(2026, 1, 20), "guarda a dose que justificou pular"
    assert _count_vaccinated_by_species(hoje) == (0, 0), "nenhuma dose saiu do frasco"
    assert PMO_STATUS_ALREADY_IMMUNE not in PMO_DOSE_STATUSES


def test_imunizado_fecha_a_casa_sem_deixar_pendencia(app, monkeypatch):
    _visita("20/01/2026", vaccine_date=date(2026, 1, 20), animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", row=3, vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente"), ("Chico", "pendente")])
    db.session.commit()

    _marcar_imunizado(app, monkeypatch, hoje.animals[0].id)
    db.session.refresh(hoje)
    assert infer_visit_status(hoje.animals) == "parcial"

    hoje.animals[1].status = "vacinado"
    db.session.commit()
    assert infer_visit_status(hoje.animals) == "vacinado"
    assert _count_vaccinated_by_species(hoje) == (1, 0), "só o Chico gastou dose"


def test_nao_da_para_marcar_imunizado_sem_dose_no_historico(app, monkeypatch):
    hoje = _visita("25/08/2026", animais=[("Chico", "pendente")])
    db.session.commit()

    with pytest.raises(ValueError, match="dose registrada"):
        _marcar_imunizado(app, monkeypatch, hoje.animals[0].id)


def test_nao_da_para_marcar_imunizado_com_dose_vencida(app, monkeypatch):
    _visita("antiga", vaccine_date=date(2024, 3, 12), animais=[("Mia", "vacinado")])
    hoje = _visita("hoje", row=3, vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente")])
    db.session.commit()

    with pytest.raises(ValueError, match="dose registrada"):
        _marcar_imunizado(app, monkeypatch, hoje.animals[0].id)


def test_a_protecao_nao_anda_para_frente_a_cada_visita(app, monkeypatch):
    """O risco central: marcar sem vacina não pode empurrar o vencimento."""
    _visita("20/01/2026", vaccine_date=date(2026, 1, 20), animais=[("Mia", "vacinado")])
    visita_2 = _visita("25/08/2026", row=3, vaccine_date=date(2026, 8, 25),
                       animais=[("Mia", "pendente")])
    db.session.commit()
    _marcar_imunizado(app, monkeypatch, visita_2.animals[0].id)

    # Terceira campanha, 10 dias ANTES de a dose real completar um ano.
    visita_3 = _visita("10/01/2027", row=4, vaccine_date=date(2027, 1, 10),
                       animais=[("Mia", "pendente")])
    db.session.commit()

    dose = build_previous_immunity_index([visita_3])[visita_3.id][visita_3.animals[0].id]
    assert dose["dateLabel"] == "20/01/2026", "a data continua sendo a da vacina de verdade"
    assert dose["protectedUntilLabel"] == "20/01/2027", (
        "a passagem por 25/08 não pode ter empurrado o vencimento para 25/08/2027"
    )
    assert dose["immune"] is True, "em 10/01/2027 a dose de 20/01/2026 ainda protege"

    # Quarta campanha, já passado o ano da dose real: precisa cobrar vacina.
    visita_4 = _visita("05/02/2027", row=5, vaccine_date=date(2027, 2, 5),
                       animais=[("Mia", "pendente")])
    db.session.commit()

    dose = build_previous_immunity_index([visita_4])[visita_4.id][visita_4.animals[0].id]
    assert dose["dateLabel"] == "20/01/2026"
    assert dose["immune"] is False, "passou de um ano da dose real: tem que vacinar"


def test_voltar_para_pendente_limpa_a_justificativa(app, monkeypatch):
    from services import vacina_pmo_service as servico

    _visita("20/01/2026", vaccine_date=date(2026, 1, 20), animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", row=3, vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente")])
    db.session.commit()
    _marcar_imunizado(app, monkeypatch, hoje.animals[0].id)
    assert hoje.animals[0].immune_since is not None

    for nome in ("write_vaccinated_counts_to_sheet", "write_note_to_sheet",
                 "write_tutor_name_color_to_sheet", "write_attended_by_to_sheet"):
        monkeypatch.setattr(servico, nome, lambda *a, **k: False)
    with app.test_request_context():
        update_vacina_pmo_animal_status(hoje.animals[0].id, "pendente")

    assert hoje.animals[0].immune_since is None


def test_observacao_registra_o_motivo_para_quem_ler_a_planilha(app, monkeypatch):
    _visita("20/01/2026", vaccine_date=date(2026, 1, 20), animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", row=3, vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente")])
    db.session.commit()
    _marcar_imunizado(app, monkeypatch, hoje.animals[0].id)

    assert "ja imunizado, sem dose" in (hoje.note or "")
    assert "20/01/2026" in (hoje.note or "")


# --------------------------------------------------------------------------
# Data informada à mão, quando o sistema não tem o registro
# --------------------------------------------------------------------------

def _marcar_imunizado_com_data(app, monkeypatch, animal_id, data):
    from services import vacina_pmo_service as servico

    for nome in ("write_vaccinated_counts_to_sheet", "write_note_to_sheet",
                 "write_tutor_name_color_to_sheet", "write_attended_by_to_sheet"):
        monkeypatch.setattr(servico, nome, lambda *a, **k: False)
    with app.test_request_context():
        return update_vacina_pmo_animal_status(
            animal_id, PMO_STATUS_ALREADY_IMMUNE, immune_since=data
        )


@pytest.mark.parametrize("digitada", ["10/03/2026", "2026-03-10", "10/03/26"])
def test_aceita_a_data_da_carteirinha_de_papel(app, monkeypatch, digitada):
    """Sem registro no sistema, vale o que o tutor mostra na carteirinha."""
    hoje = _visita("25/08/2026", vaccine_date=date(2026, 8, 25),
                   animais=[("Chico", "pendente")])
    db.session.commit()

    _marcar_imunizado_com_data(app, monkeypatch, hoje.animals[0].id, digitada)

    assert hoje.animals[0].status == PMO_STATUS_ALREADY_IMMUNE
    assert hoje.animals[0].immune_since == date(2026, 3, 10)
    assert hoje.animals[0].vaccinated_at is None
    assert _count_vaccinated_by_species(hoje) == (0, 0)


def test_data_no_futuro_e_recusada(app, monkeypatch):
    hoje = _visita("25/08/2026", vaccine_date=date(2026, 8, 25),
                   animais=[("Chico", "pendente")])
    db.session.commit()

    with pytest.raises(ValueError, match="futuro"):
        _marcar_imunizado_com_data(app, monkeypatch, hoje.animals[0].id, "10/12/2026")


def test_data_de_mais_de_um_ano_e_recusada(app, monkeypatch):
    hoje = _visita("25/08/2026", vaccine_date=date(2026, 8, 25),
                   animais=[("Chico", "pendente")])
    db.session.commit()

    with pytest.raises(ValueError, match="mais de um ano"):
        _marcar_imunizado_com_data(app, monkeypatch, hoje.animals[0].id, "01/01/2025")


def test_texto_que_nao_e_data_e_recusado(app, monkeypatch):
    hoje = _visita("25/08/2026", vaccine_date=date(2026, 8, 25),
                   animais=[("Chico", "pendente")])
    db.session.commit()

    with pytest.raises(ValueError, match="Data inválida"):
        _marcar_imunizado_com_data(app, monkeypatch, hoje.animals[0].id, "ano passado")


def test_data_digitada_vence_o_historico(app, monkeypatch):
    """O vacinador está na porta olhando o documento; ele desempata."""
    _visita("20/01/2026", vaccine_date=date(2026, 1, 20), animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", row=3, vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente")])
    db.session.commit()

    _marcar_imunizado_com_data(app, monkeypatch, hoje.animals[0].id, "05/06/2026")
    assert hoje.animals[0].immune_since == date(2026, 6, 5)


# --------------------------------------------------------------------------
# Carteirinha do tutor
# --------------------------------------------------------------------------

def test_carteirinha_mostra_protegido_e_ate_quando(app, client, monkeypatch):
    from services import vacina_pmo_service as servico

    _visita("20/01/2026", vaccine_date=date(2026, 1, 20), animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", row=3, vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente")])
    db.session.commit()
    _marcar_imunizado(app, monkeypatch, hoje.animals[0].id)
    servico._ensure_visit_public_token(hoje)
    db.session.commit()

    resposta = client.get(f"/vacina-pmo/c/{hoje.public_token}/pet/{hoje.animals[0].id}")
    html = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Já imunizado" in html, "o selo não pode dizer 'pendente'"
    assert "Vacinação pendente" not in html
    assert "20/01/2026" in html, "mostra a vacina que protege"
    assert "20/01/2027" in html, "mostra até quando protege"
    assert 'class="pill pending"' not in html


def test_carteirinha_do_vacinado_normal_nao_muda(app, client, monkeypatch):
    from services import vacina_pmo_service as servico

    hoje = _visita("25/08/2026", vaccine_date=date(2026, 8, 25),
                   animais=[("Chico", "vacinado")])
    servico._ensure_visit_public_token(hoje)
    db.session.commit()

    resposta = client.get(f"/vacina-pmo/c/{hoje.public_token}/pet/{hoje.animals[0].id}")
    html = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Vacinado" in html
    assert "25/08/2027" in html, "reforço um ano depois da dose desta visita"


def test_certificado_da_casa_nao_marca_imunizado_como_pendente(app, client, monkeypatch):
    from services import vacina_pmo_service as servico

    _visita("20/01/2026", vaccine_date=date(2026, 1, 20), animais=[("Mia", "vacinado")])
    hoje = _visita("25/08/2026", row=3, vaccine_date=date(2026, 8, 25),
                   animais=[("Mia", "pendente")])
    db.session.commit()
    _marcar_imunizado(app, monkeypatch, hoje.animals[0].id)
    servico._ensure_visit_public_token(hoje)
    db.session.commit()

    html = client.get(f"/vacina-pmo/c/{hoje.public_token}").get_data(as_text=True)
    assert "Já imunizado" in html
    assert 'class="badge pending"' not in html


def test_dose_antiga_nao_empurra_o_reforco_do_imunizado(app, client, monkeypatch):
    """Bug encontrado em produção: a carteirinha da Lupe prometia 5 meses a mais.

    O animal marcado como já imunizado tem uma vacina antiga registrada. A rota
    tratava a existência dessa vacina como "vacinado nesta visita" e contava o
    reforço a partir do dia da visita — cinco meses de proteção que ele não tem.
    """
    from datetime import datetime as _dt

    from models import Animal, Species, User, Vacina
    from services import vacina_pmo_service as servico

    tutor = User(name="Tutora Lupe", email="lupe@example.com", phone="")
    tutor.set_password("PMOA3333")
    especie = Species(name="Cachorro")
    db.session.add_all([tutor, especie])
    db.session.flush()
    animal = Animal(name="Lupe", user_id=tutor.id, species=especie, status="ativo")
    db.session.add(animal)
    db.session.flush()
    # A dose de campanha do ano passado, sem data de reforço registrada.
    db.session.add(Vacina(
        animal_id=animal.id, nome="Vacina Antirrábica", tipo="Campanha PMO",
        aplicada=True, aplicada_em=date(2026, 1, 20), criada_em=_dt(2026, 1, 20, 9, 0),
    ))

    _visita("20/01/2026", vaccine_date=date(2026, 1, 20), animais=[("Lupe", "vacinado")])
    hoje = _visita("25/08/2026", row=3, vaccine_date=date(2026, 8, 25),
                   animais=[("Lupe", "pendente")])
    hoje.animals[0].animal_id = animal.id
    db.session.commit()
    _marcar_imunizado(app, monkeypatch, hoje.animals[0].id)
    servico._ensure_visit_public_token(hoje)
    db.session.commit()

    html = client.get(
        f"/vacina-pmo/c/{hoje.public_token}/pet/{hoje.animals[0].id}"
    ).get_data(as_text=True)

    assert "20/01/2027" in html, "o reforço conta a partir da vacina de verdade"
    assert "25/08/2027" not in html, (
        "a visita sem dose não pode empurrar o vencimento um ano para frente"
    )
    assert "Vacinação pendente" not in html
