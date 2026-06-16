from services import castracao_pmo_service
from services.castracao_pmo_service import PMO_CASTRATION_REQUEST_HEADERS
from extensions import db
from models import Animal, PmoCastrationRequest, Species, User


class _FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _FakeSheetsService:
    def __init__(self, sheet_title="Solicitacoes Castracao"):
        self.sheet_title = sheet_title
        self.appended_body = None
        self.updates = []
        self.batch_updates = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        if kwargs.get("fields") == "sheets.properties":
            return _FakeExecute({
                "sheets": [{"properties": {"title": self.sheet_title, "sheetId": 654}}],
            })
        return _FakeExecute({"values": [PMO_CASTRATION_REQUEST_HEADERS]})

    def update(self, **kwargs):
        self.updates.append(kwargs)
        return _FakeExecute({})

    def batchUpdate(self, **kwargs):
        self.batch_updates.append(kwargs)
        return _FakeExecute({})

    def append(self, **kwargs):
        self.appended_body = kwargs["body"]
        return _FakeExecute({"updates": {"updatedRange": f"'{self.sheet_title}'!A2:U2"}})


def test_castracao_pmo_request_route_appends_sheet_and_creates_history(app, client, monkeypatch):
    fake_service = _FakeSheetsService()
    monkeypatch.setattr(castracao_pmo_service, "_get_sheets_service_rw", lambda: fake_service)
    monkeypatch.setenv(
        "PMO_CASTRATION_SHEET_URL",
        "https://docs.google.com/spreadsheets/d/test-sheet-id/edit",
    )

    with app.app_context():
        user = User(name="Tutor Castracao", email="castracao@example.com", phone="")
        user.set_password("123456")
        species = Species(name="Gato")
        db.session.add_all([user, species])
        db.session.flush()
        animal = Animal(
            name="Mia",
            user_id=user.id,
            species=species,
            status="ativo",
            sex="Femea",
            neutered=False,
            peso=3.2,
        )
        db.session.add(animal)
        db.session.commit()
        animal_id = animal.id

    client.post("/login", data={"login": "castracao@example.com", "password": "123456"})
    response = client.post(
        "/castracao-pmo/solicitar",
        data={
            "animal_ids": [str(animal_id)],
            "tutor": "Tutor Castracao",
            "email": "castracao@example.com",
            "cpf": "11122233344",
            "phone": "(16) 99999-9999",
            "address_street": "Rua 1",
            "address_number": "10",
            "address_neighborhood": "Centro",
            "preferred_contact": "WhatsApp",
            "female_status": "Sem cio recente",
            "health_notes": "Saudavel",
            "consent": "1",
        },
    )

    assert response.status_code == 302
    row = fake_service.appended_body["values"][0]
    assert row[0] == "Tutor Castracao"
    assert row[10:13] == ["1", "Mia", "Mia - gato - Femea - 3.2 kg - nao castrado"]
    assert row[20] == "Solicitado"

    with app.app_context():
        request_obj = PmoCastrationRequest.query.one()
        assert request_obj.tutor_name == "Tutor Castracao"
        assert request_obj.cats == 1
        assert request_obj.dogs == 0
        assert request_obj.public_token
        assert len(request_obj.animals) == 1
        assert request_obj.animals[0].name == "Mia"
