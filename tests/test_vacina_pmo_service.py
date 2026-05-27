from services.vacina_pmo_service import (
    get_vacina_pmo_public_visit,
    get_saved_vacina_pmo_rows,
    parse_vacina_pmo_rows,
    persist_vacina_pmo_rows,
    save_vacina_pmo_evaluation,
    update_vacina_pmo_animal_status,
)
from extensions import db
from models import Animal, PmoVaccinationVisit, User, Vacina


def test_parse_vacina_pmo_rows_ignores_summaries_and_dates_as_counts():
    rows = [
        [
            "Nome completo do tutor",
            "Endereço",
            "Número da casa",
            "Complemento",
            "Bairro",
            "Telefone",
            "Telefone 2",
            "Quantidade de cachorros para vacinar.",
            "Quantidade de gatos para vacinar",
            "Nome do(s) animal(is)",
            "Observação:",
            "Data Vacina",
            "Cão",
            "Gato",
            "Nome",
            "Column 16",
            "Data",
            "Turno",
        ],
        [
            "Bruno Henrique",
            "Rua 20",
            "1107",
            "Casa 73",
            "Jardim Benini",
            "16992928199",
            "16991134357",
            "1",
            "0",
            "Lunna",
            "Remarcar se ausente",
            "",
            "",
            "",
            "",
            "",
            "28/05/2026",
            "Manhã",
        ],
        ["", "", "", "", "", "", "", "10", "0", "", "", "", "0", "0"],
        ["", "", "", "", "Manhã 14:30 as 17:00", "", "", "", "", "", "", "", "", "", "", "", "28/05/2026", "Perdas"],
        ["", "", "", "", "", "", "", "", "", "", "", "", "Sobras", "", "0"],
    ]

    parsed = parse_vacina_pmo_rows(rows)

    assert len(parsed) == 1
    assert parsed[0]["tutor"] == "Bruno Henrique"
    assert parsed[0]["dogs"] == 1
    assert parsed[0]["cats"] == 0
    assert parsed[0]["date"] == "2026-05-28"
    assert parsed[0]["shift"] == "Manha"
    assert parsed[0]["animals"] == [{"name": "Lunna", "species": "cao", "status": "pendente"}]


def test_parse_vacina_pmo_rows_splits_partial_house_animals():
    rows = [
        [
            "Daiana Maria da Silva",
            "Rua 08",
            "1395",
            "",
            "Jardim boa vista",
            "99169-2393",
            "99308-0634",
            "2",
            "2",
            "Lupy e Luma",
            "",
            "",
            "",
            "",
            "",
            "",
            "28/05/2026",
            "Tarde",
        ],
    ]

    parsed = parse_vacina_pmo_rows(rows)

    assert len(parsed) == 1
    assert parsed[0]["dogs"] == 2
    assert parsed[0]["cats"] == 2
    assert [animal["name"] for animal in parsed[0]["animals"]] == [
        "Lupy",
        "Luma",
        "Gato 1",
        "Gato 2",
    ]


def test_pmo_sync_persists_and_preserves_animal_status(app):
    row = {
        "id": "sheet-1",
        "status": "pendente",
        "tutor": "Tutor PMO",
        "address": "Rua 1, 10, Centro",
        "phone1": "5516999999999",
        "phone2": "",
        "dogs": 2,
        "cats": 0,
        "animals": [
            {"name": "Lua", "species": "cao", "status": "pendente"},
            {"name": "Babi", "species": "cao", "status": "pendente"},
        ],
        "note": "",
        "date": "2026-05-28",
        "shift": "Manha",
        "password": "PMOA9999",
        "certificateUrl": "",
        "sourceRow": 2,
    }

    with app.app_context():
        saved = persist_vacina_pmo_rows(
            [row],
            spreadsheet_id="sheet-test",
            sheet_gid="123",
            sheet_title="28/05/2026",
        )
        first_animal_id = saved[0]["animals"][0]["id"]
        update_vacina_pmo_animal_status(first_animal_id, "vacinado")

        row["note"] = "observacao atualizada na planilha"
        row["animals"][0]["status"] = "pendente"
        persist_vacina_pmo_rows(
            [row],
            spreadsheet_id="sheet-test",
            sheet_gid="123",
            sheet_title="28/05/2026",
        )

        state = get_saved_vacina_pmo_rows(sheet_gid="123")
        token = PmoVaccinationVisit.query.filter_by(sheet_gid="123").first().public_token
        save_vacina_pmo_evaluation(
            token,
            5,
            "Equipe atenciosa",
            registration_rating=4,
            service_rating=5,
            information_rating=3,
            survey_rating=4,
        )
        evaluated_state = get_saved_vacina_pmo_rows(sheet_gid="123")

    assert state["rows"][0]["note"] == "observacao atualizada na planilha"
    assert state["rows"][0]["password"] == "PMOA9999"
    assert state["rows"][0]["animals"][0]["status"] == "vacinado"
    assert state["rows"][0]["status"] == "parcial"
    assert Animal.query.filter_by(name="Lua").first() is not None
    assert Vacina.query.filter_by(nome="Vacina Antirrabica", aplicada=True).first() is not None
    assert Vacina.query.filter_by(nome="Reforco Vacina Antirrabica", aplicada=False).first() is not None
    assert User.query.filter_by(phone="+5516999999999").first() is not None
    assert evaluated_state["rows"][0]["evaluationRating"] == 5
    assert evaluated_state["rows"][0]["evaluationRegistrationRating"] == 4
    assert evaluated_state["rows"][0]["evaluationServiceRating"] == 5
    assert evaluated_state["rows"][0]["evaluationInformationRating"] == 3
    assert evaluated_state["rows"][0]["evaluationSurveyRating"] == 4
    assert evaluated_state["rows"][0]["evaluationComment"] == "Equipe atenciosa"


def test_pmo_public_link_renders_and_records_evaluation(app, client, monkeypatch):
    monkeypatch.setenv("PMO_VACCINE_EDUCATIONAL_VIDEO_URL", "https://youtu.be/abcDEF12345")
    row = {
        "id": "sheet-1",
        "status": "pendente",
        "tutor": "Tutor PMO",
        "address": "Rua 1, 10, Centro",
        "phone1": "5516999999999",
        "phone2": "",
        "dogs": 1,
        "cats": 0,
        "animals": [{"name": "Lua", "species": "cao", "status": "vacinado"}],
        "note": "",
        "date": "2026-05-28",
        "shift": "Manha",
        "password": "PMOA9999",
        "certificateUrl": "",
        "sourceRow": 2,
    }

    with app.app_context():
        persist_vacina_pmo_rows(
            [row],
            spreadsheet_id="sheet-test",
            sheet_gid="123",
            sheet_title="28/05/2026",
        )
        token = PmoVaccinationVisit.query.filter_by(sheet_gid="123").first().public_token

    response = client.get(f"/vacina-pmo/c/{token}")
    assert response.status_code == 200
    assert b"Carteirinha digital da vacina" in response.data
    assert b"(16) 99999-9999" in response.data
    assert b"PMOA9999" in response.data
    assert b"Ver carteirinha" in response.data
    assert b"Comprovante simples para o tutor" in response.data
    assert b"Como usar esta carteirinha" in response.data
    assert b"Quando procurar ajuda" in response.data
    assert b"Video educativo" in response.data
    assert b"https://www.youtube.com/embed/abcDEF12345" in response.data

    post = client.post(
        f"/vacina-pmo/c/{token}",
        data={
            "rating": "5",
            "registration_rating": "4",
            "service_rating": "5",
            "information_rating": "5",
            "survey_rating": "4",
            "comment": "Atendimento excelente",
        },
    )
    assert post.status_code == 200

    with app.app_context():
        visit = get_vacina_pmo_public_visit(token)
        assert visit.evaluation_rating == 5
        assert visit.evaluation_registration_rating == 4
        assert visit.evaluation_service_rating == 5
        assert visit.evaluation_information_rating == 5
        assert visit.evaluation_survey_rating == 4
        assert visit.evaluation_comment == "Atendimento excelente"
        evaluated_state = get_saved_vacina_pmo_rows(sheet_gid="123")
        assert evaluated_state["rows"][0]["evaluationRegistrationRating"] == 4
        assert evaluated_state["rows"][0]["evaluationServiceRating"] == 5
        assert evaluated_state["rows"][0]["evaluationInformationRating"] == 5
        assert evaluated_state["rows"][0]["evaluationSurveyRating"] == 4
        assert evaluated_state["rows"][0]["evaluationComment"] == "Atendimento excelente"


def test_pmo_public_pet_card_is_tutor_friendly(app, client, monkeypatch):
    monkeypatch.setenv("PMO_VACCINE_EDUCATIONAL_VIDEO_URL", "https://www.youtube.com/watch?v=abcDEF12345")
    row = {
        "id": "sheet-1",
        "status": "pendente",
        "tutor": "Tutor PMO",
        "address": "Rua 1, 10, Centro",
        "phone1": "5516999999999",
        "phone2": "",
        "dogs": 1,
        "cats": 0,
        "animals": [{"name": "Lua", "species": "cao", "status": "vacinado"}],
        "note": "",
        "date": "2026-05-28",
        "shift": "Manha",
        "password": "PMOA9999",
        "certificateUrl": "",
        "sourceRow": 2,
    }

    with app.app_context():
        persist_vacina_pmo_rows(
            [row],
            spreadsheet_id="sheet-test",
            sheet_gid="123",
            sheet_title="28/05/2026",
        )
        visit = PmoVaccinationVisit.query.filter_by(sheet_gid="123").first()
        token = visit.public_token
        pmo_animal_id = visit.animals[0].id

    response = client.get(f"/vacina-pmo/c/{token}/pet/{pmo_animal_id}")
    assert response.status_code == 200
    assert b"Carteirinha de Lua" in response.data
    assert b"Comprovante digital da campanha" in response.data
    assert b"Proximo reforco" in response.data
    assert b"Baixar certificado em PDF" in response.data
    assert b"Imprimir pagina" in response.data
    assert b"Video educativo" not in response.data
    assert b"https://www.youtube.com/embed/abcDEF12345" not in response.data
    assert b"Abrir ficha clinica" not in response.data

    pdf_response = client.get(f"/vacina-pmo/c/{token}/pet/{pmo_animal_id}?format=pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.mimetype == "application/pdf"
    assert pdf_response.headers["Content-Disposition"].startswith("attachment;")
    assert pdf_response.data.startswith(b"%PDF")


def test_login_respects_safe_next_url(app, client):
    with app.app_context():
        user = User(name="Tutor PMO", email="tutor-pmo@example.com", phone="+5516999999999")
        user.set_password("PMOA9999")
        db.session.add(user)
        db.session.commit()

    login_page = client.get("/login?next=/animal/3070/ficha")
    assert login_page.status_code == 200
    assert b'name="next" value="/animal/3070/ficha"' in login_page.data

    response = client.post(
        "/login",
        data={
            "login": "tutor-pmo@example.com",
            "password": "PMOA9999",
            "next": "/animal/3070/ficha",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/animal/3070/ficha")

    blocked = client.get("/login?next=https://example.org/phish")
    assert b'name="next" value="/"' in blocked.data


def test_login_redirects_pmo_pet_next_to_home(app, client):
    with app.app_context():
        user = User(name="Tutor PMO", email="tutor-pmo-next@example.com", phone="+5516999999998")
        user.set_password("PMOA9998")
        db.session.add(user)
        db.session.commit()

    pmo_pet_next = "/vacina-pmo/c/kUvJU6WDQXTq6ozj9GPf9UMi3cTfXSiSNmwknKXbjos/pet/1"
    login_page = client.get(f"/login?next={pmo_pet_next}")
    assert login_page.status_code == 200
    assert b'name="next" value="/"' in login_page.data
    assert pmo_pet_next.encode() not in login_page.data

    response = client.post(
        "/login",
        data={
            "login": "tutor-pmo-next@example.com",
            "password": "PMOA9998",
            "next": pmo_pet_next,
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_pmo_visit_model_includes_evaluation_dimension_columns():
    columns = {column.name for column in PmoVaccinationVisit.__table__.columns}
    assert "evaluation_registration_rating" in columns
    assert "evaluation_service_rating" in columns
    assert "evaluation_information_rating" in columns
    assert "evaluation_survey_rating" in columns
