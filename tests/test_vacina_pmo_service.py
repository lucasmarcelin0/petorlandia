from datetime import date, timedelta

from services import vacina_pmo_service
from services.vacina_pmo_service import (
    PMO_CATS_VACCINATED_COLUMN,
    PMO_DOGS_VACCINATED_COLUMN,
    PMO_REQUEST_HEADERS,
    normalize_pmo_request_address,
    get_vacina_pmo_public_visit,
    get_saved_vacina_pmo_rows,
    parse_vacina_pmo_rows,
    persist_vacina_pmo_rows,
    save_vacina_pmo_evaluation,
    submit_vacina_pmo_request,
    update_vacina_pmo_animal_status,
)
from extensions import db
from models import Animal, PmoVaccinationVisit, Species, User, Vacina


class _FakeSheetsService:
    def __init__(self):
        self.updates = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def update(self, *, spreadsheetId, range, valueInputOption, body):
        call = {
            "spreadsheetId": spreadsheetId,
            "range": range,
            "valueInputOption": valueInputOption,
            "body": body,
        }
        self.updates.append(call)
        return self

    def execute(self):
        return {}


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


def test_normalize_pmo_request_address_splits_pasted_full_address():
    normalized = normalize_pmo_request_address({
        "address_street": "Rua 20, 1107, Cond.torino casa 73, Jardim Benini",
        "address_number": "",
        "address_complement": "",
        "address_neighborhood": "",
    })

    assert normalized["street"] == "Rua 20"
    assert normalized["number"] == "1107"
    assert normalized["complement"] == "Cond.torino casa 73"
    assert normalized["neighborhood"] == "Jardim Benini"
    assert normalized["full"] == "Rua 20, 1107, Cond.torino casa 73, Jardim Benini"


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
    assert Vacina.query.filter_by(nome="Vacina Antirrábica", aplicada=True).first() is not None
    assert Vacina.query.filter_by(nome="Reforço Vacina Antirrábica", aplicada=False).first() is not None
    assert User.query.filter_by(phone="+5516999999999").first() is not None
    assert evaluated_state["rows"][0]["evaluationRating"] == 5
    assert evaluated_state["rows"][0]["evaluationRegistrationRating"] == 4
    assert evaluated_state["rows"][0]["evaluationServiceRating"] == 5
    assert evaluated_state["rows"][0]["evaluationInformationRating"] == 3
    assert evaluated_state["rows"][0]["evaluationSurveyRating"] == 4
    assert evaluated_state["rows"][0]["evaluationComment"] == "Equipe atenciosa"


def test_submit_vacina_pmo_request_creates_local_pending_request(app, monkeypatch):
    class FakeExecute:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class FakeSheetsService:
        def __init__(self):
            self.appended_body = None

        def spreadsheets(self):
            return self

        def values(self):
            return self

        def get(self, **kwargs):
            if kwargs.get("fields") == "sheets.properties":
                return FakeExecute({"sheets": [{"properties": {"title": "Solicitacoes", "sheetId": 321}}]})
            return FakeExecute({"values": [PMO_REQUEST_HEADERS]})

        def update(self, **kwargs):
            return FakeExecute({})

        def batchUpdate(self, **kwargs):
            return FakeExecute({})

        def append(self, **kwargs):
            self.appended_body = kwargs["body"]
            return FakeExecute({"updates": {"updatedRange": "'Solicitacoes'!A2:R2"}})

    fake_service = FakeSheetsService()
    monkeypatch.setattr("services.vacina_pmo_service._get_sheets_service_rw", lambda: fake_service)
    monkeypatch.setenv("PMO_VACCINE_SHEET_URL", "https://docs.google.com/spreadsheets/d/test-sheet-id/edit")

    with app.app_context():
        user = User(name="Bruno Henrique", email="bruno-pmo@example.com", phone="+5516999999999")
        user.set_password("PMOA9999")
        db.session.add(user)
        db.session.commit()

        result = submit_vacina_pmo_request({
            "tutor": "Bruno Henrique",
            "phone": "(16) 99999-9999",
            "address_street": "Rua 20, 1107, Cond.torino casa 73, Jardim Benini",
            "address_number": "",
            "address_complement": "",
            "address_neighborhood": "",
            "dogs": 1,
            "cats": 0,
            "animal_names": "Lunna",
            "shift": "Manha",
            "note": "Remarcar visita",
            "user_id": user.id,
        })

        visit = PmoVaccinationVisit.query.filter_by(tutor_user_id=user.id, sheet_title="Solicitacoes").one()

    appended = fake_service.appended_body["values"][0]
    assert appended[1:5] == ["Rua 20", "1107", "Cond.torino casa 73", "Jardim Benini"]
    assert appended[7:10] == ["1", "0", "Lunna"]
    assert result["public_token"]
    assert visit.address == "Rua 20, 1107, Cond.torino casa 73, Jardim Benini"
    assert visit.vaccine_date is None
    assert visit.public_token == result["public_token"]


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
    assert b"Protocolo PMO-" in response.data
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
    assert b"Status da campanha" in response.data
    assert b"Dose registrada. Guarde este comprovante" in response.data
    assert b"Orientacoes depois da vacina" in response.data
    assert b"mordida ou arranhao" in response.data
    assert b"Proximo reforco" in response.data
    assert b"Contagem para o reforco" in response.data
    assert b"Faltam" in response.data or b"reforco anual esta indicado" in response.data or b"reforco anual venceu" in response.data
    assert b"Nao e necessario vacinar Lua novamente antes de completar 1 ano da dose" in response.data
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


def test_pmo_request_history_shows_only_submitted_requests(app, client):
    with app.app_context():
        user = User(name="Tutor Historico", email="tutor-historico@example.com", phone="+5516999999997")
        user.set_password("PMOA9997")
        species = Species(name="Cachorro")
        db.session.add_all([user, species])
        db.session.flush()
        animal = Animal(name="Lunna", user_id=user.id, species=species, status="ativo")
        old_campaign = PmoVaccinationVisit(
            spreadsheet_id="campaign-sheet",
            sheet_gid="123",
            sheet_title="28/05/2026",
            source_row=2,
            tutor_name=user.name,
            address="Rua antiga",
            phone1=user.phone,
            dogs=1,
            cats=0,
            vaccine_date=date(2026, 5, 28),
            password="PMOA9997",
            public_token="old-campaign-token",
            tutor_user_id=user.id,
            note="Registro antigo de campanha",
        )
        request_visit = PmoVaccinationVisit(
            spreadsheet_id="request-sheet",
            sheet_gid="321",
            sheet_title="Solicitacoes",
            source_row=3,
            tutor_name=user.name,
            address="Rua 20, 1107, Cond.torino casa 73, Jardim Benini",
            phone1=user.phone,
            dogs=1,
            cats=0,
            vaccine_date=None,
            shift="Manha",
            password="PMOA9997",
            public_token="request-token",
            tutor_user_id=user.id,
            note="Solicitacao nova",
        )
        db.session.add_all([animal, old_campaign, request_visit])
        db.session.commit()

    client.post(
        "/login",
        data={
            "login": "tutor-historico@example.com",
            "password": "PMOA9997",
        },
    )
    response = client.get("/vacina-pmo/solicitar")

    assert response.status_code == 200
    assert b"Confira antes de enviar" in response.data
    assert b"Rua 20, 1107, Cond.torino casa 73, Jardim Benini" in response.data
    assert b"PMO-" in response.data
    assert b"Abrir comprovante" in response.data
    assert b"Solicita" in response.data
    assert b"normalmente nao precisa vacinar novamente agora" in response.data
    assert b"old-campaign-token" not in response.data
    assert b"Registro antigo de campanha" not in response.data


def test_pmo_request_form_splits_saved_legacy_profile_address(app, client):
    with app.app_context():
        user = User(
            name="Tutor Endereco",
            email="tutor-endereco@example.com",
            phone="+5516999999996",
            address="Rua 20, 1107, Cond.torino casa 73, Jardim Benini",
        )
        user.set_password("PMOA9996")
        species = Species(name="Cachorro")
        db.session.add_all([user, species])
        db.session.flush()
        db.session.add(Animal(name="Lunna", user_id=user.id, species=species, status="ativo"))
        db.session.commit()

    client.post(
        "/login",
        data={
            "login": "tutor-endereco@example.com",
            "password": "PMOA9996",
        },
    )

    response = client.get("/vacina-pmo/solicitar")

    assert response.status_code == 200
    assert b'name="address_street"' in response.data
    assert b'value="Rua 20"' in response.data
    assert b'value="1107"' in response.data
    assert b'value="Cond.torino casa 73"' in response.data
    assert b'value="Jardim Benini"' in response.data
    assert b'value="Rua 20, 1107, Cond.torino casa 73, Jardim Benini"' not in response.data


def test_pmo_request_form_shows_booster_countdown_before_submission(app, client):
    with app.app_context():
        user = User(name="Tutor Reforco", email="tutor-reforco@example.com", phone="+5516999999993")
        user.set_password("PMOA9993")
        species = Species(name="Cachorro")
        db.session.add_all([user, species])
        db.session.flush()
        animal = Animal(name="Lunna", user_id=user.id, species=species, status="ativo")
        db.session.add(animal)
        db.session.flush()
        db.session.add(
            Vacina(
                animal_id=animal.id,
                nome="Vacina Antirrabica",
                tipo="Obrigatoria",
                aplicada=True,
                aplicada_em=date.today() - timedelta(days=90),
                intervalo_dias=365,
                frequencia="Anual",
            )
        )
        db.session.commit()

    client.post(
        "/login",
        data={
            "login": "tutor-reforco@example.com",
            "password": "PMOA9993",
        },
    )

    response = client.get("/vacina-pmo/solicitar")

    assert response.status_code == 200
    assert b"Lunna ja recebeu vacina antirrabica ha menos de 1 ano" in response.data
    assert b"Normalmente nao e necessario vacinar novamente antes do reforco anual" in response.data
    assert b"Faltam" in response.data
    assert b"Reforco previsto" in response.data


def test_pmo_request_form_preserves_all_fields_after_validation_error(app, client):
    with app.app_context():
        user = User(name="Tutor Campos", email="tutor-campos@example.com", phone="")
        user.set_password("PMOA9995")
        species = Species(name="Cachorro")
        db.session.add_all([user, species])
        db.session.flush()
        animal = Animal(name="Lunna", user_id=user.id, species=species, status="ativo")
        db.session.add(animal)
        db.session.commit()
        animal_id = animal.id

    client.post(
        "/login",
        data={
            "login": "tutor-campos@example.com",
            "password": "PMOA9995",
        },
    )

    response = client.post(
        "/vacina-pmo/solicitar",
        data={
            "animal_ids": [str(animal_id)],
            "tutor": "Tutor Campos Atualizado",
            "email": "campos.novo@example.com",
            "cpf": "33333333334",
            "phone": "(16) 99999-1111",
            "phone2": "(16) 98888-2222",
            "address_street": "Rua 20, 1107, Cond.torino casa 73, Jardim Benini",
            "address_number": "",
            "address_complement": "",
            "address_neighborhood": "",
            "save_address": "1",
            "shift": "",
            "note": "Portao azul, chamar no interfone",
        },
    )

    assert response.status_code == 200
    assert b"turno preferencial" in response.data
    assert b'value="Tutor Campos Atualizado"' in response.data
    assert b'value="campos.novo@example.com"' in response.data
    assert b'value="33333333334"' in response.data
    assert b'value="(16) 99999-1111"' in response.data
    assert b'value="(16) 98888-2222"' in response.data
    assert b'value="Rua 20"' in response.data
    assert b'value="1107"' in response.data
    assert b'value="Cond.torino casa 73"' in response.data
    assert b'value="Jardim Benini"' in response.data
    assert b"Portao azul, chamar no interfone" in response.data
    assert b'name="save_address"' in response.data
    assert b"checked" in response.data


def test_pmo_request_success_syncs_profile_fields_and_structured_address(app, client, monkeypatch):
    class FakeExecute:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class FakeSheetsService:
        def __init__(self):
            self.appended_body = None

        def spreadsheets(self):
            return self

        def values(self):
            return self

        def get(self, **kwargs):
            if kwargs.get("fields") == "sheets.properties":
                return FakeExecute({"sheets": [{"properties": {"title": "Solicitacoes", "sheetId": 321}}]})
            return FakeExecute({"values": [PMO_REQUEST_HEADERS]})

        def update(self, **kwargs):
            return FakeExecute({})

        def batchUpdate(self, **kwargs):
            return FakeExecute({})

        def append(self, **kwargs):
            self.appended_body = kwargs["body"]
            return FakeExecute({"updates": {"updatedRange": "'Solicitacoes'!A2:R2"}})

    fake_service = FakeSheetsService()
    monkeypatch.setattr("services.vacina_pmo_service._get_sheets_service_rw", lambda: fake_service)
    monkeypatch.setenv("PMO_VACCINE_SHEET_URL", "https://docs.google.com/spreadsheets/d/test-sheet-id/edit")

    with app.app_context():
        user = User(name="Tutor Antigo", email="tutor-sync@example.com", phone="")
        user.set_password("PMOA9994")
        species = Species(name="Cachorro")
        db.session.add_all([user, species])
        db.session.flush()
        animal = Animal(name="Lunna", user_id=user.id, species=species, status="ativo")
        db.session.add(animal)
        db.session.commit()
        user_id = user.id
        animal_id = animal.id

    client.post(
        "/login",
        data={
            "login": "tutor-sync@example.com",
            "password": "PMOA9994",
        },
    )
    response = client.post(
        "/vacina-pmo/solicitar",
        data={
            "animal_ids": [str(animal_id)],
            "tutor": "Tutor Novo",
            "email": "tutor-sync-novo@example.com",
            "cpf": "33333333335",
            "phone": "(16) 99999-3333",
            "phone2": "(16) 98888-4444",
            "address_street": "Rua 20",
            "address_number": "1107",
            "address_complement": "Cond.torino casa 73",
            "address_neighborhood": "Jardim Benini",
            "save_address": "1",
            "shift": "Manha",
            "note": "Portao azul",
        },
    )

    assert response.status_code == 302

    with app.app_context():
        user = db.session.get(User, user_id)
        visit = PmoVaccinationVisit.query.filter_by(tutor_user_id=user_id, sheet_title="Solicitacoes").one()

        assert user.name == "Tutor Novo"
        assert user.email == "tutor-sync-novo@example.com"
        assert user.cpf == "33333333335"
        assert user.phone == "(16) 99999-3333"
        assert user.address == "Rua 20, 1107, Cond.torino casa 73, Jardim Benini"
        assert user.endereco is not None
        assert user.endereco.rua == "Rua 20"
        assert user.endereco.numero == "1107"
        assert user.endereco.complemento == "Cond.torino casa 73"
        assert user.endereco.bairro == "Jardim Benini"
        assert visit.tutor_name == "Tutor Novo"
        assert visit.phone1 == "(16) 99999-3333"
        assert visit.phone2 == "(16) 98888-4444"
        assert visit.address == "Rua 20, 1107, Cond.torino casa 73, Jardim Benini"
        assert "CPF: 33333333335" in visit.note
        assert fake_service.appended_body["values"][0][1:5] == [
            "Rua 20",
            "1107",
            "Cond.torino casa 73",
            "Jardim Benini",
        ]


def test_pmo_visit_model_includes_evaluation_dimension_columns():
    columns = {column.name for column in PmoVaccinationVisit.__table__.columns}
    assert "evaluation_registration_rating" in columns
    assert "evaluation_service_rating" in columns
    assert "evaluation_information_rating" in columns
    assert "evaluation_survey_rating" in columns


def test_update_animal_status_writes_vaccinated_counts_to_source_sheet(app, monkeypatch):
    row = {
        "id": "sheet-1",
        "status": "pendente",
        "tutor": "Tutor PMO",
        "address": "Rua 1, 10, Centro",
        "phone1": "5516999999999",
        "phone2": "",
        "dogs": 2,
        "cats": 1,
        "animals": [
            {"name": "Lua", "species": "cao", "status": "pendente"},
            {"name": "Babi", "species": "cao", "status": "pendente"},
            {"name": "Mia", "species": "gato", "status": "pendente"},
        ],
        "note": "",
        "date": "2026-05-28",
        "shift": "Manha",
        "password": "PMOA9999",
        "certificateUrl": "",
        "sourceRow": 7,
    }

    fake_service = _FakeSheetsService()
    monkeypatch.setattr(
        vacina_pmo_service, "_get_sheets_service_rw", lambda: fake_service
    )

    with app.app_context():
        saved = persist_vacina_pmo_rows(
            [row],
            spreadsheet_id="planilha-pmo",
            sheet_gid="123",
            sheet_title="Vacinacao Antirrabica_7",
        )
        cao_id = next(a["id"] for a in saved[0]["animals"] if a["species"] == "cao")
        gato_id = next(a["id"] for a in saved[0]["animals"] if a["species"] == "gato")

        update_vacina_pmo_animal_status(cao_id, "vacinado")
        update_vacina_pmo_animal_status(gato_id, "vacinado")

    assert len(fake_service.updates) == 2
    last = fake_service.updates[-1]
    assert last["spreadsheetId"] == "planilha-pmo"
    assert last["range"] == (
        f"'Vacinacao Antirrabica_7'!"
        f"{PMO_DOGS_VACCINATED_COLUMN}7:{PMO_CATS_VACCINATED_COLUMN}7"
    )
    assert last["body"] == {"values": [[1, 1]]}


def test_update_animal_status_skips_sheet_write_without_sheet_metadata(app, monkeypatch):
    visit = PmoVaccinationVisit(
        spreadsheet_id="",
        sheet_gid="",
        sheet_title="",
        source_row=0,
        tutor_name="Sem planilha",
        password="PMOX0000",
    )
    db.session.add(visit)
    db.session.flush()
    from models import PmoVaccinationAnimal

    animal = PmoVaccinationAnimal(
        visit=visit, position=1, name="Rex", species="cao", status="pendente"
    )
    db.session.add(animal)
    db.session.commit()

    called = {"count": 0}

    def fake_service():
        called["count"] += 1
        return _FakeSheetsService()

    monkeypatch.setattr(vacina_pmo_service, "_get_sheets_service_rw", fake_service)

    with app.app_context():
        update_vacina_pmo_animal_status(animal.id, "vacinado")

    assert called["count"] == 0


def test_update_animal_status_swallows_sheet_failures(app, monkeypatch):
    row = {
        "id": "sheet-1",
        "status": "pendente",
        "tutor": "Tutor PMO",
        "address": "Rua 1, 10, Centro",
        "phone1": "5516999999999",
        "phone2": "",
        "dogs": 1,
        "cats": 0,
        "animals": [{"name": "Lua", "species": "cao", "status": "pendente"}],
        "note": "",
        "date": "2026-05-28",
        "shift": "Manha",
        "password": "PMOA9999",
        "certificateUrl": "",
        "sourceRow": 5,
    }

    def broken_service():
        raise RuntimeError("sheets indisponivel")

    monkeypatch.setattr(vacina_pmo_service, "_get_sheets_service_rw", broken_service)

    with app.app_context():
        saved = persist_vacina_pmo_rows(
            [row],
            spreadsheet_id="planilha-pmo",
            sheet_gid="123",
            sheet_title="Vacinacao Antirrabica_7",
        )
        animal_id = saved[0]["animals"][0]["id"]
        result = update_vacina_pmo_animal_status(animal_id, "vacinado")

    assert result["animals"][0]["status"] == "vacinado"
