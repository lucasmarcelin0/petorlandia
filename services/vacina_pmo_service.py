"""Google Sheets sync helpers for the PMO rabies vaccination campaign."""

from __future__ import annotations

import os
import re
import math
import secrets
import string
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from extensions import db
from flask import has_request_context, url_for
from models import Animal, PmoVaccinationAnimal, PmoVaccinationVisit, Species, User, Vacina
from sqlalchemy import func
from helpers import geocode_address
from services.sfa_service import (
    _extract_google_sheet_id,
    _get_sheets_service,
    _load_google_credentials_info,
    _resolve_sheet_title_by_gid,
)
from time_utils import now_in_brazil, utcnow


DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1oN74lysYpQOIYgS9nlyrQUgxa0w1FHS7yGVftpzbqAk/edit?gid=2076484491#gid=2076484491"
)
DEFAULT_SHEET_RANGE = "A:T"

PMO_VACCINE_FABRICANTE = "Bioraiva Pet (Biogenesis Bago)"
PMO_VACCINE_LOTE = "Fab. 09/2024 - Val. 09/2026"
PMO_CAMPAIGN_VET_EMAIL = "lukemarki3@gmail.com"
PMO_EDUCATIONAL_VIDEO_URL_ENV = "PMO_VACCINE_EDUCATIONAL_VIDEO_URL"
PMO_DEFAULT_EDUCATIONAL_VIDEO_URL = "https://youtu.be/lLq6ikMRbcc"

PMO_REQUEST_SHEET_TITLE_ENV = "PMO_VACCINE_REQUEST_SHEET_TITLE"
PMO_REQUEST_SHEET_DEFAULT_TITLE = "Solicitacoes"
PMO_REQUEST_HEADERS = [
    "Nome completo do tutor",
    "Endereço",
    "Número da casa",
    "Complemento (Se houver)",
    "Bairro",
    "Telefone",
    "Telefone 2 ou recado.",
    "Quantidade de cachorros para vacinar.",
    "Quantidade de gatos para vacinar",
    "Nome do(s) animal(is)",
    "Observação:",
    "Data Vacina",
    "Qtde cachorros vacinados",
    "Qtde gatos vacinados",
    "Nome",
    "Carimbo de data/hora",
    "Origem",
    "ID Usuário PetOrlandia",
]
PMO_REQUEST_RANGE_COLS = "A:R"
PMO_REQUEST_HEADER_RANGE = "A1:R1"

PMO_DOGS_VACCINATED_COLUMN = "M"
PMO_CATS_VACCINATED_COLUMN = "N"
PMO_ATTENDED_BY_COLUMN = "O"
PMO_NOTE_COLUMN = "K"
PMO_ROUTE_ORIGIN_ADDRESS_ENV = "PMO_ROUTE_ORIGIN_ADDRESS"
PMO_ROUTE_ORIGIN_LAT_ENV = "PMO_ROUTE_ORIGIN_LAT"
PMO_ROUTE_ORIGIN_LNG_ENV = "PMO_ROUTE_ORIGIN_LNG"
PMO_DEFAULT_ROUTE_ORIGIN_ADDRESS = "Vigilância Sanitária de Orlândia, SP"

# Índice 0-based da coluna A (nome do tutor) para a API de formatação do Sheets.
PMO_TUTOR_NAME_COLUMN_INDEX = 0

# Cores claras do painel padrão do Google Sheets para destacar o status da visita
# diretamente na célula do nome do tutor.
PMO_STATUS_COLORS: dict[str, dict[str, float]] = {
    # Vermelho claro: pelo menos um animal recusou a vacina.
    "recusou": {"red": 0.957, "green": 0.800, "blue": 0.800},
    # Laranja claro: pelo menos um animal ficou ausente (sem recusas).
    "ausente": {"red": 0.988, "green": 0.898, "blue": 0.804},
    # Verde claro: todos os animais foram vacinados.
    "vacinado": {"red": 0.851, "green": 0.918, "blue": 0.827},
    # Amarelo claro: vacinação parcial (alguns ainda sem desfecho positivo).
    "parcial": {"red": 1.000, "green": 0.949, "blue": 0.800},
}
# Branco "neutro": usado para limpar a cor de uma célula quando o status volta a pendente.
PMO_STATUS_CLEAR_COLOR = {"red": 1.0, "green": 1.0, "blue": 1.0}


@dataclass
class PmoSyncResult:
    rows: list[dict[str, Any]]
    spreadsheet_id: str
    sheet_range: str
    sheet_gid: str
    sheet_title: str


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_note_line(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _append_visit_note(visit: PmoVaccinationVisit, line: str) -> None:
    normalized = _normalize_note_line(line)
    if not normalized:
        return
    current = (visit.note or "").strip()
    visit.note = f"{current} | {normalized}" if current else normalized


def _pmo_event_time_label() -> str:
    return now_in_brazil().strftime("%H:%M")


def _status_note_line(animal: PmoVaccinationAnimal, status: str) -> str:
    labels = {
        "pendente": "pendente",
        "vacinado": "vacinado",
        "ausente": "ausente",
        "remarcar": "remarcar",
        "recusou": "recusou",
    }
    label = labels.get(status, status)
    return f"{_pmo_event_time_label()} - {animal.name}: {label}."


def _youtube_embed_url(url: str) -> str:
    text = _normalize_text(url)
    if not text:
        return ""
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{6,})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return f"https://www.youtube.com/embed/{match.group(1)}"
    return ""


def get_pmo_educational_video() -> dict[str, str]:
    url = os.getenv(PMO_EDUCATIONAL_VIDEO_URL_ENV, PMO_DEFAULT_EDUCATIONAL_VIDEO_URL)
    embed_url = _youtube_embed_url(url)
    if not embed_url:
        return {"url": "", "embed_url": ""}
    return {"url": url, "embed_url": embed_url}


def _strip_accents(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def _digits(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _parse_count(value: Any) -> int:
    text = _normalize_text(value)
    if not re.fullmatch(r"\d{1,2}", text):
        return 0
    parsed = int(text)
    return parsed if 0 <= parsed <= 30 else 0


def _normalize_phone(value: Any) -> str:
    digits = _digits(value)
    if not digits or digits == "0":
        return ""
    if len(digits) in {8, 9}:
        digits = f"16{digits}"
    if not digits.startswith("55"):
        digits = f"55{digits}"
    return digits if len(digits) >= 12 else ""


def _normalize_login_phone(value: Any) -> str:
    digits = _digits(value)
    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) >= 11:
        digits = digits[1:]
    return f"+55{digits}" if digits else ""


def format_pmo_phone_for_login(value: Any) -> str:
    digits = _digits(value)
    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return _normalize_text(value)


def _parse_date(value: Any) -> str:
    text = _normalize_text(value)
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return text


def _parse_date_object(value: Any) -> date | None:
    text = _parse_date(value)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalize_shift(value: Any) -> str:
    text = _strip_accents(_normalize_text(value)).lower()
    if text.startswith("man"):
        return "Manha"
    if text.startswith("tar"):
        return "Tarde"
    return _normalize_text(value)


def _pmo_address_parts(address: str) -> dict[str, str]:
    parts = [_normalize_text(part) for part in str(address or "").split(",") if _normalize_text(part)]
    return {
        "rua": parts[0] if len(parts) > 0 else "",
        "numero": parts[1] if len(parts) > 1 else "",
        "complemento": parts[2] if len(parts) > 2 else "",
        "bairro": parts[-1] if len(parts) > 3 else (parts[2] if len(parts) == 3 else ""),
    }


def _pmo_geocode_address(address: str) -> tuple[float, float] | None:
    normalized = _normalize_text(address)
    if not normalized:
        return None
    parts = _pmo_address_parts(normalized)
    return geocode_address(
        rua=parts["rua"],
        numero=parts["numero"],
        bairro=parts["bairro"],
        cidade="Orlândia",
        estado="SP",
    )


def _pmo_route_origin_address() -> str:
    return _normalize_text(os.getenv(PMO_ROUTE_ORIGIN_ADDRESS_ENV)) or PMO_DEFAULT_ROUTE_ORIGIN_ADDRESS


def _pmo_route_origin_coords() -> tuple[float, float] | None:
    try:
        lat = float(os.getenv(PMO_ROUTE_ORIGIN_LAT_ENV, ""))
        lng = float(os.getenv(PMO_ROUTE_ORIGIN_LNG_ENV, ""))
        return lat, lng
    except ValueError:
        return _pmo_geocode_address(_pmo_route_origin_address())


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(value))


def _nearest_neighbor_route(
    origin: tuple[float, float],
    items: list[tuple[PmoVaccinationVisit, tuple[float, float]]],
) -> list[PmoVaccinationVisit]:
    remaining = items[:]
    current = origin
    ordered: list[PmoVaccinationVisit] = []
    while remaining:
        next_index, (visit, coords) = min(
            enumerate(remaining),
            key=lambda item: (_haversine_km(current, item[1][1]), item[1][0].source_row or 0, item[1][0].id),
        )
        ordered.append(visit)
        current = coords
        remaining.pop(next_index)
    return ordered


def _is_summary_or_header(row: list[Any]) -> bool:
    values = [_normalize_text(item) for item in row]
    joined = " ".join(values).lower()
    first = values[0] if values else ""
    if not joined:
        return True
    if not re.search(r"[a-zA-ZÀ-ú]", first):
        return True
    return any(
        marker in joined
        for marker in (
            "nome completo do tutor",
            "total de animais",
            "digite o dia",
            "perdas",
            "sobras",
        )
    )


def _split_animals(value: Any) -> list[str]:
    text = _normalize_text(value)
    if not text:
        return []
    return [
        _normalize_text(item)
        for item in re.split(r",|;|\n|\se\s", text, flags=re.IGNORECASE)
        if _normalize_text(item)
    ]


def _build_animals(names: list[str], dogs: int, cats: int) -> list[dict[str, str]]:
    total = max(len(names), dogs + cats)
    animals: list[dict[str, str]] = []
    for index in range(total):
        species = "cao" if index < dogs else "gato"
        fallback = f"Cao {index + 1}" if species == "cao" else f"Gato {index - dogs + 1}"
        animals.append(
            {
                "name": names[index] if index < len(names) else fallback,
                "species": species,
                "status": "pendente",
            }
        )
    return animals


def _cell(row: list[Any], index: int) -> str:
    return _normalize_text(row[index]) if len(row) > index else ""


def _password(seed: str) -> str:
    suffix = (_digits(seed)[-4:] or "0000").rjust(4, "0")
    letter = secrets.choice(string.ascii_uppercase.replace("I", "").replace("O", ""))
    return f"PMO{letter}{suffix}"


def _public_token() -> str:
    return secrets.token_urlsafe(32)


def _provisional_email(phone: str, visit_id: int | None = None) -> str:
    digits = _digits(phone)[-13:] or str(visit_id or secrets.randbelow(999999)).zfill(6)
    return f"pmo-{digits}@petorlandia.local"


def _find_user_by_phone(phone: str) -> User | None:
    normalized = _normalize_login_phone(phone)
    if not normalized:
        return None
    for user in User.query.filter(User.phone.isnot(None), User.phone != "").all():
        if _normalize_login_phone(user.phone) == normalized:
            return user
    return None


def _ensure_visit_public_token(visit: PmoVaccinationVisit) -> None:
    if visit.public_token:
        return
    while True:
        token = _public_token()
        if not PmoVaccinationVisit.query.filter_by(public_token=token).first():
            visit.public_token = token
            return


def _ensure_tutor_account(visit: PmoVaccinationVisit) -> None:
    if visit.tutor_user_id:
        user = visit.tutor_user
        if user and visit.address and not user.address:
            user.address = visit.address
        return
    phone = visit.phone1 or visit.phone2
    user = _find_user_by_phone(phone)
    if user:
        visit.tutor_user = user
        if visit.address and not user.address:
            user.address = visit.address
        return
    normalized_phone = _normalize_login_phone(phone)
    if not normalized_phone:
        return
    user = User(
        name=visit.tutor_name,
        email=_provisional_email(normalized_phone, visit.id),
        phone=normalized_phone,
        role="adotante",
        address=visit.address or None,
    )
    user.set_password(visit.password)
    db.session.add(user)
    db.session.flush()
    visit.tutor_user = user


def _campaign_vet_user_id() -> int | None:
    vet = User.query.filter(func.lower(User.email) == PMO_CAMPAIGN_VET_EMAIL.lower()).first()
    return vet.id if vet else None


def _species_name(species: str) -> str:
    return "Gato" if species == "gato" else "Cachorro"


def _species_id(species: str) -> int | None:
    expected = _species_name(species)
    wanted = _strip_accents(expected).lower()
    existing = Species.query.all()
    for row in existing:
        if _strip_accents(row.name or "").lower() == wanted:
            return row.id
    created = Species(name=expected)
    db.session.add(created)
    db.session.flush()
    return created.id


def _ensure_real_animal(pmo_animal: PmoVaccinationAnimal) -> None:
    visit = pmo_animal.visit
    _ensure_tutor_account(visit)

    if pmo_animal.animal_id and not db.session.get(Animal, pmo_animal.animal_id):
        pmo_animal.animal_id = None

    if pmo_animal.animal_id or not visit.tutor_user_id:
        return

    candidate = (
        Animal.query.filter_by(user_id=visit.tutor_user_id)
        .filter(func.lower(Animal.name) == pmo_animal.name.lower())
        .first()
    )
    if candidate:
        pmo_animal.animal = candidate
        return

    animal = Animal(
        name=pmo_animal.name,
        user_id=visit.tutor_user_id,
        species_id=_species_id(pmo_animal.species),
        status="ativo",
        modo="adotado",
        description="Cadastro criado automaticamente pela campanha de vacinação antirrábica da Prefeitura de Orlândia.",
        is_alive=True,
    )
    db.session.add(animal)
    db.session.flush()
    pmo_animal.animal = animal


def _ensure_pmo_vaccine_record(pmo_animal: PmoVaccinationAnimal) -> None:
    if pmo_animal.status != "vacinado":
        return
    _ensure_real_animal(pmo_animal)
    if not pmo_animal.animal_id:
        return

    applied_date = pmo_animal.visit.vaccine_date or date.today()
    if pmo_animal.vaccine_id:
        vaccine = db.session.get(Vacina, pmo_animal.vaccine_id)
    else:
        vaccine = None
    if not vaccine:
        vaccine = (
            Vacina.query.filter(
                Vacina.animal_id == pmo_animal.animal_id,
                Vacina.nome.in_(["Vacina Antirrábica", "Vacina Antirrabica"]),
                Vacina.tipo == "Campanha PMO",
                Vacina.aplicada.is_(True),
                Vacina.aplicada_em == applied_date,
            )
            .first()
        )
    vet_id = _campaign_vet_user_id()
    if not vaccine:
        vaccine = Vacina(
            animal_id=pmo_animal.animal_id,
            nome="Vacina Antirrábica",
            tipo="Campanha PMO",
            fabricante=PMO_VACCINE_FABRICANTE,
            lote=PMO_VACCINE_LOTE,
            doses_totais=1,
            intervalo_dias=365,
            frequencia="Anual",
            aplicada=True,
            aplicada_em=applied_date,
            aplicada_por=vet_id,
            observacoes="Aplicada na campanha de vacinação antirrábica da Prefeitura de Orlândia.",
        )
        db.session.add(vaccine)
        db.session.flush()
    else:
        vaccine.nome = "Vacina Antirrábica"
        if not vaccine.fabricante or vaccine.fabricante in {"Prefeitura de Orlandia", "Prefeitura de Orlândia"}:
            vaccine.fabricante = PMO_VACCINE_FABRICANTE
        if not vaccine.lote:
            vaccine.lote = PMO_VACCINE_LOTE
        if vet_id and not vaccine.aplicada_por:
            vaccine.aplicada_por = vet_id
    pmo_animal.vaccine = vaccine

    booster_date = applied_date + timedelta(days=365)
    booster = (
        Vacina.query.filter(
            Vacina.animal_id == pmo_animal.animal_id,
            Vacina.nome.in_(["Reforço Vacina Antirrábica", "Reforco Vacina Antirrabica"]),
            Vacina.tipo.in_(["Reforço PMO", "Reforco PMO"]),
            Vacina.aplicada.is_(False),
            Vacina.aplicada_em == booster_date,
        )
        .first()
    )
    if not booster:
        db.session.add(
            Vacina(
                animal_id=pmo_animal.animal_id,
                nome="Reforço Vacina Antirrábica",
                tipo="Reforço PMO",
                fabricante=PMO_VACCINE_FABRICANTE,
                doses_totais=1,
                intervalo_dias=365,
                frequencia="Anual",
                aplicada=False,
                aplicada_em=booster_date,
                observacoes="Reforço anual previsto após a campanha PMO.",
            )
        )
    else:
        booster.nome = "Reforço Vacina Antirrábica"
        booster.tipo = "Reforço PMO"


def _ensure_visit_records(visit: PmoVaccinationVisit) -> None:
    _ensure_tutor_account(visit)
    for pmo_animal in visit.animals:
        _ensure_real_animal(pmo_animal)
        _ensure_pmo_vaccine_record(pmo_animal)


def parse_vacina_pmo_rows(values: list[list[Any]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for index, row in enumerate(values):
        if _is_summary_or_header(row):
            continue

        tutor = _cell(row, 0)
        phone1 = _normalize_phone(_cell(row, 5))
        phone2 = _normalize_phone(_cell(row, 6))
        dogs = _parse_count(_cell(row, 7))
        cats = _parse_count(_cell(row, 8))
        animals = _build_animals(_split_animals(_cell(row, 9)), dogs, cats)
        address = ", ".join(
            item for item in (_cell(row, 1), _cell(row, 2), _cell(row, 3), _cell(row, 4)) if item
        )

        if not tutor or not (phone1 or phone2 or address) or not (dogs or cats or animals):
            continue

        parsed.append(
            {
                "id": f"sheet-{index}",
                "status": "pendente",
                "tutor": tutor,
                "address": address,
                "phone1": phone1,
                "phone2": phone2,
                "dogs": dogs,
                "cats": cats,
                "animals": animals,
                "note": _cell(row, 10),
                "date": _parse_date(_cell(row, 16) or _cell(row, 11)),
                "shift": _normalize_shift(_cell(row, 17)),
                "password": _password(phone1 or phone2 or str(index)),
                "certificateUrl": "",
                "sourceRow": index + 1,
                "attendedBy": _cell(row, 14),
            }
        )
    return parsed


def _extract_gid(value: str) -> str:
    match = re.search(r"(?:gid=|#gid=)(\d+)", value or "")
    return match.group(1) if match else ""


def _quote_sheet_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _resolve_sheet_target(
    service,
    sheet_url: str,
    range_value: str,
    *,
    sheet_gid: str = "",
    sheet_title: str = "",
) -> tuple[str, str, str, str]:
    spreadsheet_id = _extract_google_sheet_id(sheet_url)
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO inválido.")

    gid = sheet_gid or os.getenv("PMO_VACCINE_SHEET_GID", "") or _extract_gid(sheet_url)
    title = sheet_title or os.getenv("PMO_VACCINE_SHEET_TITLE", "")
    if title:
        return spreadsheet_id, f"{_quote_sheet_title(title)}!{range_value}", gid, title
    if gid:
        resolved = _resolve_sheet_title_by_gid(service, spreadsheet_id, gid)
        return spreadsheet_id, f"{_quote_sheet_title(resolved)}!{range_value}", gid, resolved
    return spreadsheet_id, range_value, "", ""


def list_vacina_pmo_sheets() -> list[dict[str, Any]]:
    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    service = _get_sheets_service()
    spreadsheet_id = _extract_google_sheet_id(sheet_url)
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO inválido.")
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
        .execute()
    )
    sheets = []
    for sheet in metadata.get("sheets", []):
        props = sheet.get("properties", {})
        title = props.get("title", "")
        if not title:
            continue
        sheets.append(
            {
                "title": title,
                "gid": str(props.get("sheetId", "")),
                "date": _parse_date(title),
            }
        )
    return sheets


def infer_visit_status(animals: list[dict[str, Any]] | list[PmoVaccinationAnimal]) -> str:
    if not animals:
        return "pendente"
    statuses = [
        animal.get("status", "pendente") if isinstance(animal, dict) else (animal.status or "pendente")
        for animal in animals
    ]
    if all(status == "vacinado" for status in statuses):
        return "vacinado"
    if any(status == "vacinado" for status in statuses):
        return "parcial"
    if all(status == "ausente" for status in statuses):
        return "ausente"
    if all(status == "recusou" for status in statuses):
        return "recusou"
    if any(status == "remarcar" for status in statuses):
        return "remarcar"
    return "pendente"


def get_vacina_pmo_evaluation_payload(visit: PmoVaccinationVisit) -> dict[str, Any]:
    return {
        "rating": visit.evaluation_rating,
        "comment": visit.evaluation_comment or "",
        "registration_rating": visit.evaluation_registration_rating,
        "service_rating": visit.evaluation_service_rating,
        "information_rating": visit.evaluation_information_rating,
        "survey_rating": visit.evaluation_survey_rating,
    }


def _serialize_visit(visit: PmoVaccinationVisit) -> dict[str, Any]:
    _ensure_visit_public_token(visit)
    evaluation = get_vacina_pmo_evaluation_payload(visit)
    public_url = ""
    if has_request_context():
        public_url = url_for("vacina_pmo_public", token=visit.public_token, _external=True)
    animals = [
        {
            "id": animal.id,
            "animalId": animal.animal_id,
            "vaccineId": animal.vaccine_id,
            "name": animal.name,
            "species": animal.species,
            "status": animal.status,
        }
        for animal in visit.animals
    ]
    return {
        "id": f"visit-{visit.id}",
        "visitId": visit.id,
        "status": infer_visit_status(animals),
        "tutor": visit.tutor_name,
        "address": visit.address or "",
        "phone1": visit.phone1 or "",
        "phone2": visit.phone2 or "",
        "dogs": visit.dogs or 0,
        "cats": visit.cats or 0,
        "animals": animals,
        "note": visit.note or "",
        "date": visit.vaccine_date.isoformat() if visit.vaccine_date else "",
        "shift": visit.shift or "",
        "password": visit.password,
        "loginPhone": format_pmo_phone_for_login(visit.phone1 or visit.phone2),
        "certificateUrl": visit.certificate_url or public_url,
        "publicUrl": public_url,
        "attendedBy": visit.attended_by or "",
        "evaluationRating": evaluation["rating"],
        "evaluationRegistrationRating": evaluation["registration_rating"],
        "evaluationServiceRating": evaluation["service_rating"],
        "evaluationInformationRating": evaluation["information_rating"],
        "evaluationSurveyRating": evaluation["survey_rating"],
        "evaluationComment": evaluation["comment"],
        "evaluatedAt": visit.evaluated_at.isoformat() if visit.evaluated_at else "",
        "sourceRow": visit.source_row,
    }


def _query_sheet_visits(
    *,
    sheet_gid: str = "",
    sheet_title: str = "",
    spreadsheet_id: str = "",
):
    query = PmoVaccinationVisit.query
    if spreadsheet_id:
        query = query.filter(PmoVaccinationVisit.spreadsheet_id == spreadsheet_id)
    if sheet_gid:
        query = query.filter(PmoVaccinationVisit.sheet_gid == sheet_gid)
    if sheet_title:
        query = query.filter(PmoVaccinationVisit.sheet_title == sheet_title)
    return query


def get_saved_vacina_pmo_rows(*, sheet_gid: str = "", sheet_title: str = "") -> dict[str, Any]:
    latest = None
    if not sheet_gid and not sheet_title:
        latest = PmoVaccinationVisit.query.order_by(PmoVaccinationVisit.updated_at.desc()).first()
        if latest:
            sheet_gid = latest.sheet_gid
            sheet_title = latest.sheet_title

    visits = (
        _query_sheet_visits(sheet_gid=sheet_gid, sheet_title=sheet_title)
        .order_by(PmoVaccinationVisit.source_row.asc(), PmoVaccinationVisit.id.asc())
        .all()
    )
    for visit in visits:
        _ensure_visit_public_token(visit)
        _ensure_visit_records(visit)
    if visits:
        db.session.commit()
    return {
        "rows": [_serialize_visit(visit) for visit in visits],
        "sheet_gid": sheet_gid or (latest.sheet_gid if latest else ""),
        "sheet_title": sheet_title or (latest.sheet_title if latest else ""),
        "spreadsheet_id": visits[0].spreadsheet_id if visits else "",
    }


def optimize_vacina_pmo_route(*, sheet_gid: str = "", sheet_title: str = "", shift: str = "") -> dict[str, Any]:
    normalized_shift = _normalize_shift(shift)
    if normalized_shift not in {"Manha", "Tarde"}:
        raise ValueError("Escolha o turno Manhã ou Tarde antes de otimizar a rota.")

    latest = None
    if not sheet_gid and not sheet_title:
        latest = PmoVaccinationVisit.query.order_by(PmoVaccinationVisit.updated_at.desc()).first()
        if latest:
            sheet_gid = latest.sheet_gid
            sheet_title = latest.sheet_title

    visits = (
        _query_sheet_visits(sheet_gid=sheet_gid, sheet_title=sheet_title)
        .order_by(PmoVaccinationVisit.source_row.asc(), PmoVaccinationVisit.id.asc())
        .all()
    )
    selected = [
        visit
        for visit in visits
        if _normalize_shift(visit.shift) == normalized_shift and visit.source_row and visit.source_row > 1
    ]
    if len(selected) < 2:
        raise ValueError("Este turno precisa de pelo menos dois endereços sincronizados para otimizar.")

    spreadsheet_id = selected[0].spreadsheet_id
    resolved_gid = sheet_gid or selected[0].sheet_gid
    resolved_title = sheet_title or selected[0].sheet_title
    if not spreadsheet_id or not resolved_title:
        raise ValueError("Sincronize a aba antes de otimizar a rota.")

    origin_coords = _pmo_route_origin_coords()
    if not origin_coords:
        raise ValueError("Não foi possível localizar a Vigilância Sanitária de Orlândia para iniciar a rota.")

    geocoded: list[tuple[PmoVaccinationVisit, tuple[float, float]]] = []
    ungeocoded: list[PmoVaccinationVisit] = []
    for visit in selected:
        coords = _pmo_geocode_address(visit.address or "")
        if coords:
            geocoded.append((visit, coords))
        else:
            ungeocoded.append(visit)
    if not geocoded:
        raise ValueError("Não foi possível localizar nenhum endereço deste turno.")

    optimized = _nearest_neighbor_route(origin_coords, geocoded) + ungeocoded
    target_rows = sorted(visit.source_row for visit in selected if visit.source_row)

    service = _get_sheets_service_rw()
    range_value = f"{_quote_sheet_title(resolved_title)}!{DEFAULT_SHEET_RANGE}"
    response = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_value)
        .execute()
    )
    sheet_values = response.get("values", [])
    needed_rows = max(target_rows)
    while len(sheet_values) < needed_rows:
        sheet_values.append([])

    source_rows_by_visit_id = {
        visit.id: list(sheet_values[(visit.source_row or 1) - 1])
        for visit in selected
    }
    for destination_row, visit in zip(target_rows, optimized):
        sheet_values[destination_row - 1] = source_rows_by_visit_id.get(visit.id, [])

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_value,
        valueInputOption="USER_ENTERED",
        body={"values": sheet_values},
    ).execute()

    for visit in selected:
        visit.source_row = -visit.id
    db.session.flush()
    for destination_row, visit in zip(target_rows, optimized):
        visit.source_row = destination_row
        visit.sheet_title = resolved_title
        visit.sheet_gid = resolved_gid
    db.session.commit()

    state = get_saved_vacina_pmo_rows(sheet_gid=resolved_gid, sheet_title=resolved_title)
    return {
        **state,
        "shift": normalized_shift,
        "origin": _pmo_route_origin_address(),
        "optimized_count": len(optimized),
        "unlocated_count": len(ungeocoded),
    }


def persist_vacina_pmo_rows(
    rows: list[dict[str, Any]],
    *,
    spreadsheet_id: str,
    sheet_gid: str,
    sheet_title: str,
) -> list[dict[str, Any]]:
    now = utcnow()
    saved: list[PmoVaccinationVisit] = []
    for row in rows:
        source_row = int(row.get("sourceRow") or 0)
        if source_row <= 0:
            continue

        visit = (
            PmoVaccinationVisit.query.filter_by(
                spreadsheet_id=spreadsheet_id,
                sheet_gid=sheet_gid,
                source_row=source_row,
            )
            .first()
        )
        if not visit:
            visit = PmoVaccinationVisit(
                spreadsheet_id=spreadsheet_id,
                sheet_gid=sheet_gid,
                source_row=source_row,
                password=row.get("password") or _password(row.get("phone1") or row.get("phone2") or source_row),
            )
            db.session.add(visit)

        visit.sheet_title = sheet_title
        visit.tutor_name = row.get("tutor") or ""
        visit.address = row.get("address") or ""
        visit.phone1 = row.get("phone1") or ""
        visit.phone2 = row.get("phone2") or ""
        visit.dogs = int(row.get("dogs") or 0)
        visit.cats = int(row.get("cats") or 0)
        visit.vaccine_date = _parse_date_object(row.get("date"))
        visit.shift = row.get("shift") or ""
        visit.note = row.get("note") or ""
        visit.attended_by = (row.get("attendedBy") or "").strip() or None
        visit.synced_at = now
        _ensure_visit_public_token(visit)

        existing_by_position = {animal.position: animal for animal in visit.animals}
        parsed_animals = row.get("animals") or []
        keep_positions = set()
        for position, animal_data in enumerate(parsed_animals, start=1):
            animal = existing_by_position.get(position)
            if not animal:
                animal = PmoVaccinationAnimal(
                    visit=visit,
                    position=position,
                    status=animal_data.get("status") or "pendente",
                )
                db.session.add(animal)
            animal.name = animal_data.get("name") or f"Animal {position}"
            animal.species = animal_data.get("species") or "cao"
            keep_positions.add(position)

        for position, animal in list(existing_by_position.items()):
            if position not in keep_positions:
                db.session.delete(animal)

        _ensure_visit_records(visit)

        saved.append(visit)

    db.session.commit()
    return [_serialize_visit(visit) for visit in saved]


def _count_vaccinated_by_species(visit: PmoVaccinationVisit) -> tuple[int, int]:
    dogs = sum(1 for animal in visit.animals if animal.species == "cao" and animal.status == "vacinado")
    cats = sum(1 for animal in visit.animals if animal.species == "gato" and animal.status == "vacinado")
    return dogs, cats


def write_vaccinated_counts_to_sheet(visit: PmoVaccinationVisit) -> bool:
    """Escreve as quantidades vacinadas (M=cães, N=gatos) na linha de origem do tutor."""
    if not visit.spreadsheet_id or not visit.source_row:
        return False
    if not visit.sheet_title and not visit.sheet_gid:
        return False

    dogs_vac, cats_vac = _count_vaccinated_by_species(visit)

    try:
        service = _get_sheets_service_rw()
    except Exception:
        from flask import current_app
        try:
            current_app.logger.warning(
                "Falha ao iniciar cliente Sheets para gravar contagens PMO", exc_info=True
            )
        except Exception:
            pass
        return False

    try:
        title = visit.sheet_title
        if not title and visit.sheet_gid:
            title = _resolve_sheet_title_by_gid(service, visit.spreadsheet_id, visit.sheet_gid)
        if not title:
            return False
        range_value = (
            f"{_quote_sheet_title(title)}!"
            f"{PMO_DOGS_VACCINATED_COLUMN}{visit.source_row}:"
            f"{PMO_CATS_VACCINATED_COLUMN}{visit.source_row}"
        )
        service.spreadsheets().values().update(
            spreadsheetId=visit.spreadsheet_id,
            range=range_value,
            valueInputOption="USER_ENTERED",
            body={"values": [[dogs_vac, cats_vac]]},
        ).execute()
        return True
    except Exception:
        from flask import current_app
        try:
            current_app.logger.warning(
                "Falha ao atualizar contagens de vacinados na planilha PMO", exc_info=True
            )
        except Exception:
            pass
        return False


def write_note_to_sheet(visit: PmoVaccinationVisit) -> bool:
    """Escreve a observação acumulada na célula K da linha de origem do tutor."""
    if not visit.spreadsheet_id or not visit.source_row:
        return False
    if not visit.sheet_title and not visit.sheet_gid:
        return False

    try:
        service = _get_sheets_service_rw()
    except Exception:
        from flask import current_app
        try:
            current_app.logger.warning(
                "Falha ao iniciar cliente Sheets para gravar observação PMO", exc_info=True
            )
        except Exception:
            pass
        return False

    try:
        title = visit.sheet_title
        if not title and visit.sheet_gid:
            title = _resolve_sheet_title_by_gid(service, visit.spreadsheet_id, visit.sheet_gid)
        if not title:
            return False
        range_value = f"{_quote_sheet_title(title)}!{PMO_NOTE_COLUMN}{visit.source_row}"
        service.spreadsheets().values().update(
            spreadsheetId=visit.spreadsheet_id,
            range=range_value,
            valueInputOption="USER_ENTERED",
            body={"values": [[visit.note or ""]]},
        ).execute()
        return True
    except Exception:
        from flask import current_app
        try:
            current_app.logger.warning(
                "Falha ao atualizar observação na planilha PMO", exc_info=True
            )
        except Exception:
            pass
        return False


def _visit_status_color_key(visit: PmoVaccinationVisit) -> str | None:
    """Retorna a chave de cor (vermelho, laranja, verde, amarelo) para o status da visita.

    Precedência (do sinal mais "preocupante" para o melhor):
        recusou > ausente > vacinado (todos) > parcial (algum vacinado) > None
    Quando nenhuma cor é necessária (pendente/remarcar puro) devolve ``None`` para
    indicar que a célula deve voltar ao neutro.
    """
    statuses = [animal.status for animal in (visit.animals or [])]
    if not statuses:
        return None
    if any(status == "recusou" for status in statuses):
        return "recusou"
    if any(status == "ausente" for status in statuses):
        return "ausente"
    if all(status == "vacinado" for status in statuses):
        return "vacinado"
    if any(status == "vacinado" for status in statuses):
        return "parcial"
    return None


def write_tutor_name_color_to_sheet(visit: PmoVaccinationVisit) -> bool:
    """Pinta a célula do nome do tutor (coluna A) conforme o status da visita."""
    if not visit.spreadsheet_id or not visit.source_row:
        return False
    if not visit.sheet_gid:
        return False
    try:
        sheet_id = int(visit.sheet_gid)
    except (TypeError, ValueError):
        return False

    try:
        service = _get_sheets_service_rw()
    except Exception:
        from flask import current_app
        try:
            current_app.logger.warning(
                "Falha ao iniciar cliente Sheets para pintar nome do tutor PMO",
                exc_info=True,
            )
        except Exception:
            pass
        return False

    color_key = _visit_status_color_key(visit)
    color = PMO_STATUS_COLORS.get(color_key) if color_key else PMO_STATUS_CLEAR_COLOR

    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=visit.spreadsheet_id,
            body={
                "requests": [
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": visit.source_row - 1,
                                "endRowIndex": visit.source_row,
                                "startColumnIndex": PMO_TUTOR_NAME_COLUMN_INDEX,
                                "endColumnIndex": PMO_TUTOR_NAME_COLUMN_INDEX + 1,
                            },
                            "cell": {
                                "userEnteredFormat": {"backgroundColor": color},
                            },
                            "fields": "userEnteredFormat.backgroundColor",
                        }
                    }
                ]
            },
        ).execute()
        return True
    except Exception:
        from flask import current_app
        try:
            current_app.logger.warning(
                "Falha ao pintar célula do tutor na planilha PMO", exc_info=True
            )
        except Exception:
            pass
        return False


def update_vacina_pmo_animal_status(animal_id: int, status: str) -> dict[str, Any]:
    allowed = {"pendente", "vacinado", "ausente", "remarcar", "recusou"}
    if status not in allowed:
        raise ValueError("Status inválido.")
    animal = PmoVaccinationAnimal.query.get_or_404(animal_id)
    animal.status = status
    animal.vaccinated_at = utcnow() if status == "vacinado" else None
    _append_visit_note(animal.visit, _status_note_line(animal, status))
    _ensure_real_animal(animal)
    _ensure_pmo_vaccine_record(animal)
    db.session.commit()
    write_vaccinated_counts_to_sheet(animal.visit)
    write_note_to_sheet(animal.visit)
    write_tutor_name_color_to_sheet(animal.visit)
    return _serialize_visit(animal.visit)


def append_vacina_pmo_visit_note(visit_id: int, note: str) -> dict[str, Any]:
    """Acrescenta uma observação manual sem apagar o histórico anterior."""
    visit = PmoVaccinationVisit.query.get_or_404(visit_id)
    normalized = _normalize_note_line(note)
    if not normalized:
        raise ValueError("Digite uma observação antes de salvar.")
    if len(normalized) > 500:
        raise ValueError("A observação deve ter no máximo 500 caracteres.")
    _append_visit_note(visit, f"{_pmo_event_time_label()} - {normalized}")
    db.session.commit()
    write_note_to_sheet(visit)
    return _serialize_visit(visit)


def write_attended_by_to_sheet(visit: PmoVaccinationVisit) -> bool:
    """Escreve o nome de quem atendeu (coluna O) na linha de origem do tutor."""
    if not visit.spreadsheet_id or not visit.source_row:
        return False
    if not visit.sheet_title and not visit.sheet_gid:
        return False

    try:
        service = _get_sheets_service_rw()
    except Exception:
        from flask import current_app
        try:
            current_app.logger.warning(
                "Falha ao iniciar cliente Sheets para gravar 'atendido por' PMO", exc_info=True
            )
        except Exception:
            pass
        return False

    try:
        title = visit.sheet_title
        if not title and visit.sheet_gid:
            title = _resolve_sheet_title_by_gid(service, visit.spreadsheet_id, visit.sheet_gid)
        if not title:
            return False
        range_value = (
            f"{_quote_sheet_title(title)}!"
            f"{PMO_ATTENDED_BY_COLUMN}{visit.source_row}"
        )
        service.spreadsheets().values().update(
            spreadsheetId=visit.spreadsheet_id,
            range=range_value,
            valueInputOption="USER_ENTERED",
            body={"values": [[visit.attended_by or ""]]},
        ).execute()
        return True
    except Exception:
        from flask import current_app
        try:
            current_app.logger.warning(
                "Falha ao atualizar 'atendido por' na planilha PMO", exc_info=True
            )
        except Exception:
            pass
        return False


def update_vacina_pmo_visit_attended_by(visit_id: int, attended_by: str | None) -> dict[str, Any]:
    """Atualiza quem atendeu o vacinador na visita e grava na planilha (coluna O)."""
    visit = PmoVaccinationVisit.query.get_or_404(visit_id)
    normalized = (attended_by or "").strip()
    if len(normalized) > 255:
        raise ValueError("O nome de quem atendeu deve ter no máximo 255 caracteres.")
    visit.attended_by = normalized or None
    db.session.commit()
    write_attended_by_to_sheet(visit)
    return _serialize_visit(visit)


def get_vacina_pmo_public_visit(token: str) -> PmoVaccinationVisit | None:
    visit = PmoVaccinationVisit.query.filter_by(public_token=token).first()
    if visit:
        _ensure_visit_public_token(visit)
        _ensure_visit_records(visit)
        db.session.commit()
    return visit


def _validate_optional_rating(value: Any, label: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        rating = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"A nota de {label} precisa ficar entre 1 e 5.")
    if rating < 1 or rating > 5:
        raise ValueError(f"A nota de {label} precisa ficar entre 1 e 5.")
    return rating


def save_vacina_pmo_evaluation(
    token: str,
    rating: int,
    comment: str = "",
    *,
    registration_rating: int | None = None,
    service_rating: int | None = None,
    information_rating: int | None = None,
    survey_rating: int | None = None,
) -> PmoVaccinationVisit:
    visit = PmoVaccinationVisit.query.filter_by(public_token=token).first_or_404()
    if rating < 1 or rating > 5:
        raise ValueError("A nota precisa ficar entre 1 e 5.")
    registration_rating = _validate_optional_rating(registration_rating, "cadastro e agendamento")
    service_rating = _validate_optional_rating(service_rating, "atendimento no dia")
    information_rating = _validate_optional_rating(information_rating, "informações")
    survey_rating = _validate_optional_rating(survey_rating, "pesquisa")
    visit.evaluation_rating = rating
    visit.evaluation_registration_rating = registration_rating
    visit.evaluation_service_rating = service_rating
    visit.evaluation_information_rating = information_rating
    visit.evaluation_survey_rating = survey_rating
    visit.evaluation_comment = (comment or "").strip()[:1200]
    visit.evaluated_at = utcnow()
    db.session.commit()
    return visit


def sync_vacina_pmo_sheet(*, sheet_gid: str = "", sheet_title: str = "") -> PmoSyncResult:
    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    range_value = os.getenv("PMO_VACCINE_SHEET_RANGE", DEFAULT_SHEET_RANGE)
    service = _get_sheets_service()
    spreadsheet_id, sheet_range, resolved_gid, resolved_title = _resolve_sheet_target(
        service,
        sheet_url,
        range_value,
        sheet_gid=sheet_gid,
        sheet_title=sheet_title,
    )
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=sheet_range)
        .execute()
    )
    rows = parse_vacina_pmo_rows(result.get("values", []))
    return PmoSyncResult(
        rows=rows,
        spreadsheet_id=spreadsheet_id,
        sheet_range=sheet_range,
        sheet_gid=resolved_gid,
        sheet_title=resolved_title,
    )


def _get_sheets_service_rw():
    """Sheets client with read/write scope for the PMO spreadsheet."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "google-api-python-client nao instalado. "
            "Execute: pip install google-api-python-client google-auth"
        ) from exc

    info = _load_google_credentials_info()
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)


def _ensure_request_sheet(service, spreadsheet_id: str, title: str) -> None:
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
        .execute()
    )
    existing = {
        sheet["properties"].get("title", ""): sheet["properties"]
        for sheet in metadata.get("sheets", [])
    }
    if title not in existing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {"addSheet": {"properties": {"title": title}}}
                ]
            },
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet_title(title)}!A1",
            valueInputOption="RAW",
            body={"values": [PMO_REQUEST_HEADERS]},
        ).execute()
        return

    header_response = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet_title(title)}!{PMO_REQUEST_HEADER_RANGE}",
        )
        .execute()
    )
    current_header = (header_response.get("values") or [[]])[0]
    if [_normalize_text(item) for item in current_header] != PMO_REQUEST_HEADERS:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet_title(title)}!A1",
            valueInputOption="RAW",
            body={"values": [PMO_REQUEST_HEADERS]},
        ).execute()


def _get_sheet_gid(service, spreadsheet_id: str, title: str) -> str:
    """Retorna o sheetId (gid) de uma aba pelo título."""
    try:
        metadata = (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
            .execute()
        )
        for sheet in metadata.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == title:
                return str(props.get("sheetId", ""))
    except Exception:
        pass
    return ""


def normalize_pmo_request_address(payload: dict[str, Any]) -> dict[str, str]:
    """Normaliza endereco do formulario, inclusive quando tudo foi colado na rua."""
    street = _normalize_text(payload.get("address_street"))
    number = _normalize_text(payload.get("address_number"))
    complement = _normalize_text(payload.get("address_complement"))
    neighborhood = _normalize_text(payload.get("address_neighborhood"))

    parts = [_normalize_text(part) for part in street.split(",") if _normalize_text(part)]
    if len(parts) >= 3 and (not number or not neighborhood):
        street = parts[0]
        if not number:
            number = parts[1]
        middle = parts[2:]
        if not neighborhood and middle:
            neighborhood = middle[-1]
            middle = middle[:-1]
        if not complement and middle:
            complement = ", ".join(middle)

    return {
        "street": street,
        "number": number,
        "complement": complement,
        "neighborhood": neighborhood,
        "full": ", ".join(part for part in [street, number, complement, neighborhood] if part),
    }


def submit_vacina_pmo_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Acrescenta uma nova solicitação do morador na aba de solicitações.

    Além de gravar na planilha, cria um registro local ``PmoVaccinationVisit``
    vinculado ao usuário para que o histórico fique disponível na plataforma.
    """
    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    spreadsheet_id = _extract_google_sheet_id(sheet_url)
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO inválido.")

    title = os.getenv(PMO_REQUEST_SHEET_TITLE_ENV, PMO_REQUEST_SHEET_DEFAULT_TITLE)
    address = normalize_pmo_request_address(payload)

    service = _get_sheets_service_rw()
    _ensure_request_sheet(service, spreadsheet_id, title)

    submitted_at = utcnow()
    timestamp = submitted_at.astimezone().strftime("%d/%m/%Y %H:%M:%S")

    note_parts: list[str] = []
    shift_value = _normalize_text(payload.get("shift"))
    if shift_value:
        note_parts.append(f"Turno preferencial: {shift_value}")
    user_note = _normalize_text(payload.get("note"))
    if user_note:
        note_parts.append(user_note)
    contact_email = _normalize_text(payload.get("email"))
    if contact_email:
        note_parts.append(f"E-mail: {contact_email}")
    cpf_value = _normalize_text(payload.get("cpf"))
    if cpf_value:
        note_parts.append(f"CPF: {cpf_value}")
    observacao = " | ".join(note_parts)

    row = [
        _normalize_text(payload.get("tutor")),
        address["street"],
        address["number"],
        address["complement"],
        address["neighborhood"],
        _normalize_text(payload.get("phone")),
        _normalize_text(payload.get("phone2")),
        str(int(payload.get("dogs") or 0)),
        str(int(payload.get("cats") or 0)),
        _normalize_text(payload.get("animal_names")),
        observacao,
        "",
        "",
        "",
        "",
        timestamp,
        "PetOrlandia",
        str(payload.get("user_id") or ""),
    ]

    response = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet_title(title)}!{PMO_REQUEST_RANGE_COLS}",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        )
        .execute()
    )

    updated_range = response.get("updates", {}).get("updatedRange", "")

    # Determina o número da linha inserida para compor o source_row
    source_row = 0
    import re as _re
    m = _re.search(r"!A(\d+)", updated_range)
    if m:
        source_row = int(m.group(1))

    # Obtém o gid da aba de solicitações
    sheet_gid = _get_sheet_gid(service, spreadsheet_id, title)

    # Cria (ou atualiza) o registro local para histórico e protocolo
    public_token: str | None = None
    user_id = payload.get("user_id")
    if source_row and sheet_gid is not None:
        try:
            existing = PmoVaccinationVisit.query.filter_by(
                spreadsheet_id=spreadsheet_id,
                sheet_gid=sheet_gid,
                source_row=source_row,
            ).first()

            if existing is None:
                visit = PmoVaccinationVisit(
                    spreadsheet_id=spreadsheet_id,
                    sheet_gid=sheet_gid,
                    sheet_title=title,
                    source_row=source_row,
                    tutor_name=_normalize_text(payload.get("tutor")),
                    address=address["full"],
                    phone1=_normalize_text(payload.get("phone")),
                    phone2=_normalize_text(payload.get("phone2")),
                    dogs=int(payload.get("dogs") or 0),
                    cats=int(payload.get("cats") or 0),
                    vaccine_date=None,
                    note=observacao,
                    shift=shift_value,
                    password=_password(payload.get("phone") or payload.get("phone2") or source_row),
                    tutor_user_id=int(user_id) if user_id else None,
                    synced_at=submitted_at,
                    updated_at=submitted_at,
                )
                _ensure_visit_public_token(visit)
                db.session.add(visit)
                db.session.commit()
                public_token = visit.public_token
            else:
                existing.tutor_name = _normalize_text(payload.get("tutor"))
                existing.address = address["full"]
                existing.phone1 = _normalize_text(payload.get("phone"))
                existing.phone2 = _normalize_text(payload.get("phone2"))
                existing.dogs = int(payload.get("dogs") or 0)
                existing.cats = int(payload.get("cats") or 0)
                existing.note = observacao
                existing.shift = shift_value
                existing.synced_at = submitted_at
                existing.updated_at = submitted_at
                if existing.tutor_user_id is None and user_id:
                    existing.tutor_user_id = int(user_id)
                _ensure_visit_public_token(existing)
                db.session.commit()
                public_token = existing.public_token
        except Exception:
            db.session.rollback()

    return {
        "spreadsheet_id": spreadsheet_id,
        "sheet_title": title,
        "updated_range": updated_range,
        "public_token": public_token,
        "address": address,
        "submitted_at": submitted_at.isoformat(),
    }
