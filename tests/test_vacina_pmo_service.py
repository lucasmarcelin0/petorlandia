from datetime import date, timedelta

from services import vacina_pmo_service
from services.vacina_pmo_service import (
    append_vacina_pmo_visit_note,
    PMO_ATTENDED_BY_COLUMN,
    PMO_CATS_VACCINATED_COLUMN,
    PMO_DOGS_VACCINATED_COLUMN,
    PMO_NOTE_COLUMN,
    PMO_REQUEST_HEADERS,
    normalize_pmo_request_address,
    get_vacina_pmo_public_visit,
    get_saved_vacina_pmo_rows,
    optimize_vacina_pmo_route,
    preview_vacina_pmo_route,
    parse_vacina_pmo_rows,
    persist_vacina_pmo_rows,
    save_vacina_pmo_evaluation,
    submit_vacina_pmo_request,
    undo_last_vacina_pmo_route_optimization,
    update_vacina_pmo_animal_status,
    update_vacina_pmo_visit_attended_by,
)
from extensions import db
from models import Animal, PmoRouteOptimizationBackup, PmoVaccinationVisit, Species, User, Vacina


class _FakeSheetsService:
    def __init__(self, sheet_values=None):
        self.updates = []
        self.batch_updates = []
        self.sheet_values = sheet_values or []

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
        if range.endswith("!A:T"):
            self.sheet_values = body.get("values", [])
        else:
            import re

            match = re.search(r"!A(\d+):R\1$", range)
            if match:
                row_number = int(match.group(1))
                while len(self.sheet_values) < row_number:
                    self.sheet_values.append([])
                current_tail = self.sheet_values[row_number - 1][18:]
                self.sheet_values[row_number - 1] = (body.get("values") or [[]])[0] + current_tail
        return self

    def get(self, *, spreadsheetId, range, **kwargs):
        if range.endswith("!A:R"):
            return _FakeSheetsExecute({"values": [row[:18] for row in self.sheet_values]})
        return _FakeSheetsExecute({"values": self.sheet_values})

    def batchUpdate(self, *, spreadsheetId, body):
        call = {"spreadsheetId": spreadsheetId, "body": body}
        self.batch_updates.append(call)
        return self

    def execute(self):
        return {}


class _FakeSheetsExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


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


def test_parse_vacina_pmo_rows_does_not_split_conjunction_inside_description():
    # Regressão: a tutora descreveu os 2 gatos como
    # "Branca (mais nova e braba) Princesa (mais velha e calma)". O " e " dentro
    # dos parênteses NÃO pode virar separador, ou apareceriam 3 animais fantasmas
    # e a visita ficaria "parcial" (amarela) mesmo todos vacinados.
    rows = [
        [
            "Dulcineia Alves da Silva Pereira",
            "Avenida D.",
            "1384",
            "Casa.",
            "Jardim Boa Vista",
            "99998-4368",
            "99998-0634",
            "0",
            "2",
            "Branca (mais nova e braba) Princesa (mais velha e calma)",
            "",
            "",
            "",
            "",
            "",
            "",
            "03/06/2026",
            "Tarde",
        ],
    ]

    parsed = parse_vacina_pmo_rows(rows)

    assert len(parsed) == 1
    assert parsed[0]["dogs"] == 0
    assert parsed[0]["cats"] == 2
    # A contagem oficial (2 gatos) manda: exatamente 2 animais, sem fantasmas.
    assert len(parsed[0]["animals"]) == 2
    assert all(animal["species"] == "gato" for animal in parsed[0]["animals"])


def test_parse_vacina_pmo_rows_caps_animals_to_official_count():
    # Mesmo que o texto livre produza nomes demais (vírgula dentro da descrição),
    # a quantidade informada na planilha limita o número de animais.
    rows = [
        [
            "Fulano de Tal",
            "Rua X",
            "10",
            "",
            "Centro",
            "16999990000",
            "",
            "1",
            "0",
            "Rex, o grande, valente",
            "",
            "",
            "",
            "",
            "",
            "",
            "01/06/2026",
            "Manhã",
        ],
    ]

    parsed = parse_vacina_pmo_rows(rows)

    assert len(parsed) == 1
    assert len(parsed[0]["animals"]) == 1
    assert parsed[0]["animals"][0]["species"] == "cao"


def test_parse_vacina_pmo_rows_reads_request_date_column():
    rows = [
        [
            "5/29/2026",
            "Leni Maria Mendes",
            "Alameda 22",
            "1921",
            "",
            "Jardim sao Joao",
            "16994597803",
            "16993080634",
            "2",
            "0",
            "Luther e bela",
            "Eles nao sao bravo mas exige focinheira",
            "",
            "",
            "",
            "",
            "",
            "5/29/2026",
            "Manha",
        ],
    ]

    parsed = parse_vacina_pmo_rows(rows)

    assert len(parsed) == 1
    assert parsed[0]["tutor"] == "Leni Maria Mendes"
    assert parsed[0]["requestedDate"] == "2026-05-29"
    assert parsed[0]["date"] == "2026-05-29"
    assert parsed[0]["dogs"] == 2
    assert [animal["name"] for animal in parsed[0]["animals"]] == ["Luther", "bela"]


def test_pmo_address_queries_try_google_like_variants():
    queries = vacina_pmo_service._pmo_address_queries(
        "Avenida H 792 - (Avenida 23 205 - antigo), 792, Casa da esquina, Gruta"
    )

    joined = "\n".join(queries)
    assert "Orlândia, SP, Brasil" in joined
    assert "Gruta" in joined
    assert "Avenida H 792" in joined
    assert any("Gruta, Orlândia" in query for query in queries)


def test_pmo_extract_best_nominatim_coords_prefers_orlandia_bounds():
    payload = [
        {"lat": "-23.55", "lon": "-46.63", "display_name": "Rua 1, São Paulo, Brasil"},
        {"lat": "-20.7166", "lon": "-47.8614", "display_name": "Rua 1, Orlândia, São Paulo, Brasil"},
    ]

    assert vacina_pmo_service._pmo_extract_best_nominatim_coords(payload) == (-20.7166, -47.8614)


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
        "requestedDate": "2026-05-25",
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
    assert state["rows"][0]["requestedDate"] == "2026-05-25"
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


def test_pmo_sync_relinks_when_sheet_row_changes_tutor_and_animals(app):
    first_row = {
        "id": "sheet-1",
        "status": "pendente",
        "tutor": "Ana Carolina Pereira",
        "address": "Cond. Paris, 6, Jardim Morada do Sol",
        "phone1": "5516992978934",
        "phone2": "5516999678334",
        "dogs": 1,
        "cats": 0,
        "animals": [{"name": "Lilica", "species": "cao", "status": "pendente"}],
        "note": "",
        "date": "2026-05-30",
        "shift": "Manha",
        "password": "PMOA8934",
        "certificateUrl": "",
        "sourceRow": 4,
    }
    changed_row = {
        **first_row,
        "tutor": "Elis Regina Sestari",
        "phone1": "5516981436364",
        "phone2": "5516981436364",
        "dogs": 0,
        "cats": 2,
        "animals": [
            {"name": "Pretinho", "species": "gato", "status": "pendente"},
            {"name": "Th\u00e9o", "species": "gato", "status": "pendente"},
        ],
    }

    with app.app_context():
        persist_vacina_pmo_rows(
            [first_row],
            spreadsheet_id="sheet-test",
            sheet_gid="123",
            sheet_title="30/05/2026",
        )
        ana = User.query.filter_by(name="Ana Carolina Pereira").one()
        assert [animal.name for animal in ana.animals] == ["Lilica"]

        persist_vacina_pmo_rows(
            [changed_row],
            spreadsheet_id="sheet-test",
            sheet_gid="123",
            sheet_title="30/05/2026",
        )

        ana_animals = [animal.name for animal in ana.animals]
        elis = User.query.filter_by(name="Elis Regina Sestari").one()
        elis_animals = sorted(animal.name for animal in elis.animals)
        visit = PmoVaccinationVisit.query.filter_by(source_row=4).one()
        visit_tutor_name = visit.tutor_user.name
        linked_tutor_names = [animal.animal.owner.name for animal in visit.animals]

    assert ana_animals == ["Lilica"]
    assert elis_animals == ["Pretinho", "Th\u00e9o"]
    assert visit_tutor_name == "Elis Regina Sestari"
    assert linked_tutor_names == ["Elis Regina Sestari", "Elis Regina Sestari"]


def test_optimize_vacina_pmo_route_reorders_shift_in_sheet_and_state(app, monkeypatch):
    rows = [
        {
            "id": "sheet-1",
            "status": "pendente",
            "tutor": "Tutor Longe",
            "address": "Rua Longe, 30, Centro",
            "phone1": "5516999999991",
            "phone2": "",
            "dogs": 1,
            "cats": 0,
            "animals": [{"name": "Longe", "species": "cao", "status": "pendente"}],
            "note": "",
            "date": "2026-05-28",
            "shift": "Manha",
            "password": "PMOA9991",
            "certificateUrl": "",
            "sourceRow": 2,
        },
        {
            "id": "sheet-2",
            "status": "pendente",
            "tutor": "Tutor Perto",
            "address": "Rua Perto, 10, Centro",
            "phone1": "5516999999992",
            "phone2": "",
            "dogs": 1,
            "cats": 0,
            "animals": [{"name": "Perto", "species": "cao", "status": "pendente"}],
            "note": "",
            "date": "2026-05-28",
            "shift": "Manha",
            "password": "PMOA9992",
            "certificateUrl": "",
            "sourceRow": 3,
        },
        {
            "id": "sheet-3",
            "status": "pendente",
            "tutor": "Tutor Meio",
            "address": "Rua Meio, 20, Centro",
            "phone1": "5516999999993",
            "phone2": "",
            "dogs": 1,
            "cats": 0,
            "animals": [{"name": "Meio", "species": "cao", "status": "pendente"}],
            "note": "",
            "date": "2026-05-28",
            "shift": "Manha",
            "password": "PMOA9993",
            "certificateUrl": "",
            "sourceRow": 4,
        },
        {
            "id": "sheet-4",
            "status": "pendente",
            "tutor": "Tutor Tarde",
            "address": "Rua Tarde, 40, Centro",
            "phone1": "5516999999994",
            "phone2": "",
            "dogs": 1,
            "cats": 0,
            "animals": [{"name": "Tarde", "species": "cao", "status": "pendente"}],
            "note": "",
            "date": "2026-05-28",
            "shift": "Tarde",
            "password": "PMOA9994",
            "certificateUrl": "",
            "sourceRow": 5,
        },
    ]
    def sheet_row(tutor, street, number, neighborhood, animal, date, shift, tail):
        row = [tutor, street, number, "", neighborhood, "16999999999", "", 1, 0, animal, "", "", "", "", "", "", date, shift]
        return row + tail

    fake_service = _FakeSheetsService([
        ["Nome completo do tutor", "Endereço"],
        sheet_row("Tutor Longe", "Rua Longe", "30", "Centro", "Longe", "28/05/2026", "Manhã", ["whatsapp-longe-1", "whatsapp-longe-2"]),
        sheet_row("Tutor Perto", "Rua Perto", "10", "Centro", "Perto", "28/05/2026", "Manhã", ["whatsapp-perto-1", "whatsapp-perto-2"]),
        sheet_row("Tutor Meio", "Rua Meio", "20", "Centro", "Meio", "28/05/2026", "Manhã", ["whatsapp-meio-1", "whatsapp-meio-2"]),
        sheet_row("Tutor Tarde", "Rua Tarde", "40", "Centro", "Tarde", "28/05/2026", "Tarde", ["whatsapp-tarde-1", "whatsapp-tarde-2"]),
    ])
    coords = {
        "Rua Perto, 10, Centro": (0.0, 1.0),
        "Rua Meio, 20, Centro": (0.0, 2.0),
        "Rua Longe, 30, Centro": (0.0, 3.0),
    }
    monkeypatch.setattr(vacina_pmo_service, "_get_sheets_service_rw", lambda: fake_service)
    monkeypatch.setattr(vacina_pmo_service, "_pmo_route_origin_coords", lambda: (0.0, 0.0))
    monkeypatch.setattr(vacina_pmo_service, "_pmo_geocode_address", lambda address: coords.get(address))

    with app.app_context():
        persist_vacina_pmo_rows(
            rows,
            spreadsheet_id="sheet-test",
            sheet_gid="123",
            sheet_title="28/05/2026",
        )
        preview = preview_vacina_pmo_route(sheet_gid="123", sheet_title="28/05/2026", shift="Manhã")
        assert [item["tutor"] for item in preview["preview"]] == ["Tutor Perto", "Tutor Meio", "Tutor Longe"]
        assert fake_service.updates == []

        result = optimize_vacina_pmo_route(sheet_gid="123", sheet_title="28/05/2026", shift="Manhã")

    morning = [row["tutor"] for row in result["rows"] if row["shift"] == "Manha"]
    assert morning == ["Tutor Perto", "Tutor Meio", "Tutor Longe"]
    assert result["optimized_count"] == 3
    assert result["unlocated_count"] == 0
    assert fake_service.sheet_values[1][0] == "Tutor Perto"
    assert fake_service.sheet_values[2][0] == "Tutor Meio"
    assert fake_service.sheet_values[3][0] == "Tutor Longe"
    assert fake_service.sheet_values[4][0] == "Tutor Tarde"
    assert fake_service.sheet_values[1][18:] == ["whatsapp-longe-1", "whatsapp-longe-2"]
    assert fake_service.sheet_values[2][18:] == ["whatsapp-perto-1", "whatsapp-perto-2"]
    assert fake_service.sheet_values[3][18:] == ["whatsapp-meio-1", "whatsapp-meio-2"]
    assert fake_service.sheet_values[4][18:] == ["whatsapp-tarde-1", "whatsapp-tarde-2"]
    assert all(not update["range"].endswith("!A:T") for update in fake_service.updates)

    with app.app_context():
        backup = PmoRouteOptimizationBackup.query.filter_by(sheet_gid="123", shift="Manha").first()
        assert backup is not None
        undo = undo_last_vacina_pmo_route_optimization(sheet_gid="123", sheet_title="28/05/2026", shift="Manhã")

    morning_after_undo = [row["tutor"] for row in undo["rows"] if row["shift"] == "Manha"]
    assert morning_after_undo == ["Tutor Longe", "Tutor Perto", "Tutor Meio"]
    assert fake_service.sheet_values[1][0] == "Tutor Longe"
    assert fake_service.sheet_values[2][0] == "Tutor Perto"
    assert fake_service.sheet_values[3][0] == "Tutor Meio"
    assert fake_service.sheet_values[1][18:] == ["whatsapp-longe-1", "whatsapp-longe-2"]


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
    monkeypatch.setattr(vacina_pmo_service, "_pmo_event_time_label", lambda: "09:15")

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

    count_updates = [call for call in fake_service.updates if call["range"].endswith(f"{PMO_DOGS_VACCINATED_COLUMN}7:{PMO_CATS_VACCINATED_COLUMN}7")]
    note_updates = [call for call in fake_service.updates if call["range"].endswith(f"{PMO_NOTE_COLUMN}7")]
    assert len(count_updates) == 2
    assert len(note_updates) == 2
    last_count = count_updates[-1]
    assert last_count["spreadsheetId"] == "planilha-pmo"
    assert last_count["range"] == (
        f"'Vacinacao Antirrabica_7'!"
        f"{PMO_DOGS_VACCINATED_COLUMN}7:{PMO_CATS_VACCINATED_COLUMN}7"
    )
    assert last_count["body"] == {"values": [[1, 1]]}
    assert note_updates[-1]["body"] == {"values": [["09:15 - Lua: vacinado. | 09:15 - Mia: vacinado."]]}


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


def test_append_visit_note_preserves_existing_observation_in_same_cell(app, monkeypatch):
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
        "note": "Portão azul",
        "date": "2026-05-28",
        "shift": "Manha",
        "password": "PMOA9999",
        "certificateUrl": "",
        "sourceRow": 6,
    }

    fake_service = _FakeSheetsService()
    monkeypatch.setattr(
        vacina_pmo_service, "_get_sheets_service_rw", lambda: fake_service
    )
    monkeypatch.setattr(vacina_pmo_service, "_pmo_event_time_label", lambda: "10:40")

    with app.app_context():
        saved = persist_vacina_pmo_rows(
            [row],
            spreadsheet_id="planilha-pmo",
            sheet_gid="123",
            sheet_title="Vacinacao Antirrabica_7",
        )
        result = append_vacina_pmo_visit_note(saved[0]["visitId"], " ligar no horário do almoço ")

    assert result["note"] == "Portão azul | 10:40 - ligar no horário do almoço"
    assert fake_service.updates[-1]["range"] == f"'Vacinacao Antirrabica_7'!{PMO_NOTE_COLUMN}6"
    assert fake_service.updates[-1]["body"] == {
        "values": [["Portão azul | 10:40 - ligar no horário do almoço"]]
    }


def test_update_attended_by_writes_name_to_column_o(app, monkeypatch):
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
        "sourceRow": 9,
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
        visit_id = saved[0]["visitId"]
        result = update_vacina_pmo_visit_attended_by(visit_id, "  João Maria  ")

    assert result["attendedBy"] == "João Maria"
    assert len(fake_service.updates) == 1
    update = fake_service.updates[0]
    assert update["spreadsheetId"] == "planilha-pmo"
    assert update["range"] == (
        f"'Vacinacao Antirrabica_7'!{PMO_ATTENDED_BY_COLUMN}9"
    )
    assert update["body"] == {"values": [["João Maria"]]}


def test_update_attended_by_clears_value_when_empty(app, monkeypatch):
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
        "sourceRow": 4,
        "attendedBy": "Vizinho Pedro",
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
        assert saved[0]["attendedBy"] == "Vizinho Pedro"
        visit_id = saved[0]["visitId"]
        result = update_vacina_pmo_visit_attended_by(visit_id, "")

    assert result["attendedBy"] == ""
    visit = PmoVaccinationVisit.query.get(visit_id)
    assert visit.attended_by is None
    assert fake_service.updates[-1]["body"] == {"values": [[""]]}


def _color_request(body):
    return body["requests"][0]["repeatCell"]


def _color_dict(body):
    return _color_request(body)["cell"]["userEnteredFormat"]["backgroundColor"]


def test_status_color_all_vaccinated_paints_green(app, monkeypatch):
    from services.vacina_pmo_service import PMO_STATUS_COLORS

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
        "sourceRow": 5,
    }

    fake = _FakeSheetsService()
    monkeypatch.setattr(vacina_pmo_service, "_get_sheets_service_rw", lambda: fake)

    with app.app_context():
        saved = persist_vacina_pmo_rows(
            [row],
            spreadsheet_id="planilha-pmo",
            sheet_gid="123",
            sheet_title="Vacinacao_5",
        )
        ids = [a["id"] for a in saved[0]["animals"]]
        update_vacina_pmo_animal_status(ids[0], "vacinado")
        update_vacina_pmo_animal_status(ids[1], "vacinado")

    assert len(fake.batch_updates) == 2
    last = fake.batch_updates[-1]
    assert last["spreadsheetId"] == "planilha-pmo"
    range_ = _color_request(last["body"])["range"]
    assert range_["sheetId"] == 123
    assert range_["startRowIndex"] == 4 and range_["endRowIndex"] == 5
    assert range_["startColumnIndex"] == 0 and range_["endColumnIndex"] == 1
    assert _color_dict(last["body"]) == PMO_STATUS_COLORS["vacinado"]


def test_status_color_partial_paints_yellow(app, monkeypatch):
    from services.vacina_pmo_service import PMO_STATUS_COLORS

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
        "sourceRow": 6,
    }

    fake = _FakeSheetsService()
    monkeypatch.setattr(vacina_pmo_service, "_get_sheets_service_rw", lambda: fake)

    with app.app_context():
        saved = persist_vacina_pmo_rows(
            [row],
            spreadsheet_id="planilha-pmo",
            sheet_gid="321",
            sheet_title="Vacinacao_6",
        )
        first_id = saved[0]["animals"][0]["id"]
        update_vacina_pmo_animal_status(first_id, "vacinado")

    last = fake.batch_updates[-1]
    assert _color_dict(last["body"]) == PMO_STATUS_COLORS["parcial"]


def test_status_color_recusou_overrides_vaccinated_with_red(app, monkeypatch):
    from services.vacina_pmo_service import PMO_STATUS_COLORS

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
        "sourceRow": 8,
    }

    fake = _FakeSheetsService()
    monkeypatch.setattr(vacina_pmo_service, "_get_sheets_service_rw", lambda: fake)

    with app.app_context():
        saved = persist_vacina_pmo_rows(
            [row],
            spreadsheet_id="planilha-pmo",
            sheet_gid="555",
            sheet_title="Vacinacao_8",
        )
        ids = [a["id"] for a in saved[0]["animals"]]
        update_vacina_pmo_animal_status(ids[0], "vacinado")
        update_vacina_pmo_animal_status(ids[1], "recusou")

    last = fake.batch_updates[-1]
    assert _color_dict(last["body"]) == PMO_STATUS_COLORS["recusou"]


def test_status_color_ausente_paints_orange(app, monkeypatch):
    from services.vacina_pmo_service import PMO_STATUS_COLORS

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
        "sourceRow": 11,
    }

    fake = _FakeSheetsService()
    monkeypatch.setattr(vacina_pmo_service, "_get_sheets_service_rw", lambda: fake)

    with app.app_context():
        saved = persist_vacina_pmo_rows(
            [row],
            spreadsheet_id="planilha-pmo",
            sheet_gid="777",
            sheet_title="Vacinacao_11",
        )
        update_vacina_pmo_animal_status(saved[0]["animals"][0]["id"], "ausente")

    last = fake.batch_updates[-1]
    assert _color_dict(last["body"]) == PMO_STATUS_COLORS["ausente"]


def test_status_color_back_to_pendente_clears_to_white(app, monkeypatch):
    from services.vacina_pmo_service import PMO_STATUS_CLEAR_COLOR

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
        "sourceRow": 12,
    }

    fake = _FakeSheetsService()
    monkeypatch.setattr(vacina_pmo_service, "_get_sheets_service_rw", lambda: fake)

    with app.app_context():
        saved = persist_vacina_pmo_rows(
            [row],
            spreadsheet_id="planilha-pmo",
            sheet_gid="999",
            sheet_title="Vacinacao_12",
        )
        animal_id = saved[0]["animals"][0]["id"]
        update_vacina_pmo_animal_status(animal_id, "vacinado")
        update_vacina_pmo_animal_status(animal_id, "pendente")

    assert _color_dict(fake.batch_updates[-1]["body"]) == PMO_STATUS_CLEAR_COLOR


# ——— Criar dia de vacinação ————————————————————————————————————————————————

def test_distribute_pmo_houses_respects_shift_targets():
    houses = [{"sourceRow": i, "dogs": 1, "cats": 1} for i in range(1, 16)]

    plan = vacina_pmo_service.distribute_pmo_houses(houses)

    # Manhã enche até a meta (~14 animais), tarde leva o resto até ~25 no total.
    assert len(plan["Manha"]) == 7
    assert len(plan["Tarde"]) == 5
    assert plan["manha_animals"] == 14
    assert plan["tarde_animals"] == 10
    assert [h["sourceRow"] for h in plan["Manha"]] == [1, 2, 3, 4, 5, 6, 7]
    assert [h["sourceRow"] for h in plan["Tarde"]] == [8, 9, 10, 11, 12]


def test_distribute_pmo_houses_never_exceeds_template_rows():
    houses = [{"sourceRow": i, "dogs": 1, "cats": 0} for i in range(1, 40)]

    plan = vacina_pmo_service.distribute_pmo_houses(houses)

    assert len(plan["Manha"]) <= 9
    assert len(plan["Tarde"]) <= 9


def test_empty_shift_slots_skips_header_and_summary_rows():
    def _row(turno, first=""):
        row = [""] * 18
        row[0] = first
        row[17] = turno
        return row

    values = [
        _row("Turno"),            # linha 1: cabeçalho
        _row("Manhã"),            # linha 2: vaga manhã
        _row("Manhã"),            # linha 3: vaga manhã
        _row("Manhã", "Resumo"),  # linha 4: A preenchido -> ignora
        _row("Tarde"),            # linha 5: vaga tarde
    ]

    assert vacina_pmo_service._pmo_empty_shift_slots(values, "Manha") == [2, 3]
    assert vacina_pmo_service._pmo_empty_shift_slots(values, "Tarde") == [5]


def test_scheduled_rows_from_backgrounds_detects_painted_rows():
    backgrounds = [
        None,                                           # linha 1: sem cor
        {"red": 1.0, "green": 1.0, "blue": 1.0},        # linha 2: branca
        {"red": 0.851, "green": 0.918, "blue": 0.827},  # linha 3: verde -> agendada
    ]

    assert vacina_pmo_service._pmo_scheduled_rows_from_backgrounds(backgrounds) == {3}


def test_pmo_color_is_white():
    assert vacina_pmo_service._pmo_color_is_white(None) is True
    assert vacina_pmo_service._pmo_color_is_white({"red": 0.95, "green": 0.95, "blue": 0.95}) is True
    assert vacina_pmo_service._pmo_color_is_white({"red": 0.851, "green": 0.918, "blue": 0.827}) is False


class _FakeMetaService:
    def __init__(self, titles):
        self.titles = titles

    def spreadsheets(self):
        return self

    def get(self, *, spreadsheetId, fields):
        self._payload = {"sheets": [{"properties": {"title": t}} for t in self.titles]}
        return self

    def execute(self):
        return self._payload


def test_resolve_pmo_sheet_title_is_tolerant_to_case_accent_spaces():
    svc = _FakeMetaService(["Inscrições  a Agendar ", "padrão", "Agendadas"])

    assert (
        vacina_pmo_service._resolve_pmo_sheet_title(svc, "X", "inscrições a agendar")
        == "Inscrições  a Agendar "
    )
    assert vacina_pmo_service._resolve_pmo_sheet_title(svc, "X", "PADRAO") == "padrão"


def test_resolve_pmo_sheet_title_lists_available_tabs_on_failure():
    import pytest

    svc = _FakeMetaService(["Respostas ao formulário", "Agendadas"])
    with pytest.raises(ValueError) as exc:
        vacina_pmo_service._resolve_pmo_sheet_title(svc, "X", "inscrições a agendar")

    message = str(exc.value)
    assert "Respostas ao formulário" in message
    assert "Agendadas" in message


def _pmo_house(source_row, *, endereco="", complemento="", dogs=1, cats=0):
    cells = [""] * 11
    cells[1] = endereco      # B
    cells[3] = complemento   # D
    return {"sourceRow": source_row, "dogs": dogs, "cats": cats, "cells": cells}


def test_pmo_is_condo_detects_keyword_in_complement():
    assert vacina_pmo_service._pmo_is_condo(_pmo_house(1, complemento="Condomínio Torino"))
    assert vacina_pmo_service._pmo_is_condo(_pmo_house(2, complemento="A - Condominio Quebec Casa 182"))
    assert not vacina_pmo_service._pmo_is_condo(_pmo_house(3, complemento="Casa"))
    assert not vacina_pmo_service._pmo_is_condo(_pmo_house(4, complemento=""))


def test_plan_pmo_day_groups_first_condo_in_morning_and_skips_others():
    houses = [
        _pmo_house(1, endereco="Rua 20 - 1107", complemento="Condomínio Torino"),
        _pmo_house(2, endereco="Rua 20 - 1107", complemento="Condomínio Torino"),
        _pmo_house(3, endereco="Rua 20 - 1107", complemento="Condomínio Torino"),
        _pmo_house(4, endereco="Rua 20 955A", complemento="Condomínio Quebec"),
        _pmo_house(5, endereco="Rua 20 955A", complemento="Condomínio Quebec"),
        _pmo_house(6, complemento="Casa"),
        _pmo_house(7),
        _pmo_house(8),
        _pmo_house(9),
        _pmo_house(10),
        _pmo_house(11),
        _pmo_house(12),
    ]

    plan = vacina_pmo_service.plan_pmo_day(houses)

    assert plan["condo"] == "Torino"
    manha_src = [h["sourceRow"] for h in plan["Manha"]]
    tarde_src = [h["sourceRow"] for h in plan["Tarde"]]
    # As 3 unidades do Torino abrem a manhã, juntas.
    assert manha_src[:3] == [1, 2, 3]
    # O outro condomínio (Quebec, linhas 4 e 5) fica de fora do dia.
    assert 4 not in manha_src + tarde_src
    assert 5 not in manha_src + tarde_src


def test_plan_pmo_day_groups_condo_units_despite_messy_complement():
    houses = [
        _pmo_house(1, endereco="Rua 20 955A ", complemento="Condomínio Quebec. Casa 87"),
        _pmo_house(2, endereco="Rua 20 955A", complemento="A - Condominio Quebec Casa 182"),
        _pmo_house(3, endereco="rua 20 955a", complemento="Condomínio Quebec  - Casa 85"),
        _pmo_house(4, complemento="Casa"),
    ]

    plan = vacina_pmo_service.plan_pmo_day(houses)

    assert plan["condo"] == "Quebec"
    condo_units = [h for h in plan["Manha"] if vacina_pmo_service._pmo_is_condo(h)]
    assert sorted(h["sourceRow"] for h in condo_units) == [1, 2, 3]


def test_build_animals_truncates_overlong_name_to_db_limit():
    # Regressão: cadastro com muitos nomes em texto livre (todos entre parênteses)
    # virava um único nome gigante e estourava o varchar(120), derrubando o sync.
    long_name = "(" + ", ".join(f"Bicho{i}" for i in range(40)) + ") gatos e cães"
    assert len(long_name) > 120

    animals = vacina_pmo_service._build_animals([long_name], 0, 1)

    assert len(animals) == 1
    assert len(animals[0]["name"]) <= 120


def test_pmo_is_master_sheet_matches_ignoring_accent_and_case():
    assert vacina_pmo_service._pmo_is_master_sheet("Vacinação 2026")
    assert vacina_pmo_service._pmo_is_master_sheet("vacinacao 2026")
    assert vacina_pmo_service._pmo_is_master_sheet("  Vacinação  2026 ")
    assert not vacina_pmo_service._pmo_is_master_sheet("03/06/2026")
    assert not vacina_pmo_service._pmo_is_master_sheet("Inscrição a agendar")
    assert not vacina_pmo_service._pmo_is_master_sheet("")
