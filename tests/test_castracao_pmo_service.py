import pytest
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


class _FakeCastracaoSheets:
    """Planilha falsa que registra abas criadas e o destino do append."""

    def __init__(self, titles, castracao_title=None):
        self.titles = list(titles)
        self.created_titles = []
        self.append_range = ""
        # Qual aba realmente guarda o cabeçalho de castração (21 colunas).
        self.castracao_title = castracao_title

    def spreadsheets(self):
        return self

    def values(self):
        return self

    class _Execute:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    def get(self, **kwargs):
        if kwargs.get("fields") == "sheets.properties":
            return self._Execute(
                {
                    "sheets": [
                        {"properties": {"title": t, "sheetId": 200 + i}}
                        for i, t in enumerate(self.titles)
                    ]
                }
            )
        from services.castracao_pmo_service import PMO_CASTRATION_REQUEST_HEADERS

        return self._Execute({"values": [PMO_CASTRATION_REQUEST_HEADERS]})

    def batchGet(self, **kwargs):
        from services.castracao_pmo_service import PMO_CASTRATION_REQUEST_HEADERS
        from services.vacina_pmo_service import PMO_REQUEST_HEADERS

        faixas = []
        for faixa in kwargs["ranges"]:
            aba = faixa.split("!")[0].strip("'")
            cabecalho = (
                PMO_CASTRATION_REQUEST_HEADERS
                if aba == self.castracao_title
                else PMO_REQUEST_HEADERS
            )
            faixas.append({"values": [cabecalho]})
        return self._Execute({"valueRanges": faixas})

    def update(self, **kwargs):
        return self._Execute({})

    def batchUpdate(self, **kwargs):
        for item in kwargs.get("body", {}).get("requests", []):
            titulo = item.get("addSheet", {}).get("properties", {}).get("title")
            if titulo:
                self.created_titles.append(titulo)
                self.titles.append(titulo)
        return self._Execute({})

    def append(self, **kwargs):
        self.append_range = kwargs["range"]
        aba = kwargs["range"].split("!")[0].strip("'")
        return self._Execute({"updates": {"updatedRange": f"'{aba}'!A2:U2"}})


@pytest.mark.parametrize(
    "titulo_existente",
    ["Solicitacoes Castracao", "Solicitações Castração", "Solicitacoes de castracao"],
)
def test_castracao_grava_na_aba_renomeada_sem_criar_copia(app, monkeypatch, titulo_existente):
    """Renomear a aba não pode esconder as inscrições de castração.

    Aqui o risco é maior que na vacina: não há painel nem sincronização, então
    essa aba é a única janela da equipe para as inscrições.
    """
    from services import castracao_pmo_service

    fake = _FakeCastracaoSheets(
        ["Vacinação 2026", titulo_existente, "Solicitacoes de vacina"],
        castracao_title=titulo_existente,
    )
    monkeypatch.setattr(castracao_pmo_service, "_get_sheets_service_rw", lambda: fake)
    monkeypatch.delenv("PMO_CASTRATION_REQUEST_SHEET_TITLE", raising=False)

    resolvido = castracao_pmo_service._resolve_castration_request_sheet_title(
        fake, "test-sheet-id", castracao_pmo_service.pmo_castration_request_sheet_titles()[0]
    )

    assert fake.created_titles == []
    assert resolvido == titulo_existente


def test_castracao_nao_reaproveita_a_aba_da_vacina(app, monkeypatch):
    """Sem aba de castração, cria a dela — nunca escreve na aba da vacina."""
    from services import castracao_pmo_service
    from services.vacina_pmo_service import PMO_REQUEST_HEADERS

    class _SoVacina(_FakeCastracaoSheets):
        def get(self, **kwargs):
            if kwargs.get("fields") == "sheets.properties":
                return super().get(**kwargs)
            # Qualquer aba existente devolve o cabeçalho da VACINA (21 != 18).
            return self._Execute({"values": [PMO_REQUEST_HEADERS]})

        def batchGet(self, **kwargs):
            return self._Execute(
                {"valueRanges": [{"values": [PMO_REQUEST_HEADERS]} for _ in kwargs["ranges"]]}
            )

    fake = _SoVacina(["Vacinação 2026", "Solicitacoes de vacina"])
    monkeypatch.setattr(castracao_pmo_service, "_get_sheets_service_rw", lambda: fake)
    monkeypatch.delenv("PMO_CASTRATION_REQUEST_SHEET_TITLE", raising=False)

    resolvido = castracao_pmo_service._resolve_castration_request_sheet_title(
        fake, "test-sheet-id", castracao_pmo_service.pmo_castration_request_sheet_titles()[0]
    )

    assert resolvido == "Solicitacoes Castracao"
    assert fake.created_titles == ["Solicitacoes Castracao"]
