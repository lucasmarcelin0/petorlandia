from services.sfa_service import (
    _extract_google_sheet_gid,
    _extract_google_sheet_id,
    _resolve_sinan_sheet_target,
)


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeSpreadsheets:
    def __init__(self, payload):
        self._payload = payload

    def get(self, **_kwargs):
        return _FakeRequest(self._payload)


class _FakeService:
    def __init__(self, payload):
        self._payload = payload

    def spreadsheets(self):
        return _FakeSpreadsheets(self._payload)


def test_extract_google_sheet_id_from_url():
    value = "https://docs.google.com/spreadsheets/d/12jeuBTWlE4NT6Ni9Ha_t2vERdGPOwPMgZCjuXNGvzfk/edit?gid=1339975360#gid=1339975360"

    assert _extract_google_sheet_id(value) == "12jeuBTWlE4NT6Ni9Ha_t2vERdGPOwPMgZCjuXNGvzfk"


def test_extract_google_sheet_gid_from_url():
    value = "https://docs.google.com/spreadsheets/d/12jeuBTWlE4NT6Ni9Ha_t2vERdGPOwPMgZCjuXNGvzfk/edit?gid=1339975360#gid=1339975360"

    assert _extract_google_sheet_gid(value) == "1339975360"


def test_resolve_sinan_sheet_target_uses_gid_metadata(monkeypatch):
    monkeypatch.setattr(
        "services.sfa_service.SHEET_ID_SINAN",
        "https://docs.google.com/spreadsheets/d/12jeuBTWlE4NT6Ni9Ha_t2vERdGPOwPMgZCjuXNGvzfk/edit?gid=1339975360#gid=1339975360",
    )
    monkeypatch.setattr("services.sfa_service.SHEET_RANGE_SINAN", "A:T")
    monkeypatch.setattr("services.sfa_service.SHEET_TITLE_SINAN", "")
    monkeypatch.setattr("services.sfa_service.SHEET_GID_SINAN", "")
    service = _FakeService(
        {
            "sheets": [
                {"properties": {"sheetId": 1339975360, "title": "SINAN Atualizado"}},
            ]
        }
    )

    spreadsheet_id, sheet_range = _resolve_sinan_sheet_target(service)

    assert spreadsheet_id == "12jeuBTWlE4NT6Ni9Ha_t2vERdGPOwPMgZCjuXNGvzfk"
    assert sheet_range == "'SINAN Atualizado'!A:T"
