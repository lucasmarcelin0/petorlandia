"""Google Sheets sync helpers for the PMO rabies vaccination campaign."""

from __future__ import annotations

import os
import re
import math
import json
import secrets
import string
import unicodedata
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import requests
from extensions import db
from flask import has_request_context, url_for
from models import (
    Animal,
    PmoRouteOptimizationBackup,
    PmoVaccinationAnimal,
    PmoVaccinationVisit,
    Species,
    User,
    Vacina,
)
from sqlalchemy import func
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
PMO_ANIMAL_NAMES_COLUMN = "J"

# Aba mestre de status (mantida pelo sync agendado). O app NUNCA deve escrever
# nela — a coluna M ali é o "Status PMO" compilado, não a contagem do app.
PMO_MASTER_SHEET_TITLE = os.getenv("PMO_VACCINE_MASTER_SHEET_TITLE", "Vacinação 2026")

# Aba de controle de doses/estoque mantida à mão (fonte oficial de vacinados/perdas).
PMO_DOSES_SHEET_TITLE_ENV = "PMO_VACCINE_DOSES_SHEET_TITLE"
PMO_DOSES_SHEET_DEFAULT_TITLE = "Controle de doses"
_PMO_MONTHS = [
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

# Limite de nome de animal. O cadastro flui para duas colunas: pmo_vaccination_animal.name
# (varchar 120) e animal.name (varchar 100). Usamos o menor (100) para caber em ambas.
# Cadastros com muitos nomes em texto livre geram um "nome" gigante; truncar evita
# estourar o banco e derrubar a sincronização inteira.
PMO_ANIMAL_NAME_MAX = 100
PMO_ROUTE_ORIGIN_ADDRESS_ENV = "PMO_ROUTE_ORIGIN_ADDRESS"
PMO_ROUTE_ORIGIN_LAT_ENV = "PMO_ROUTE_ORIGIN_LAT"
PMO_ROUTE_ORIGIN_LNG_ENV = "PMO_ROUTE_ORIGIN_LNG"
PMO_DEFAULT_ROUTE_ORIGIN_ADDRESS = "Vigilância Sanitária Municipal, Rua Um, 17, Centro, Orlândia, SP, 14620-000"
PMO_DEFAULT_ROUTE_ORIGIN_COORDS = (-20.7122478, -47.8838617)
PMO_ROUTE_GEOCODE_LIMIT_ENV = "PMO_ROUTE_GEOCODE_LIMIT"
PMO_ROUTE_GEOCODE_VARIANTS_ENV = "PMO_ROUTE_GEOCODE_VARIANTS"
PMO_ORLANDIA_BOUNDS = {
    "min_lat": -20.86,
    "max_lat": -20.55,
    "min_lng": -48.08,
    "max_lng": -47.68,
}

# Índice 0-based da coluna A (nome do tutor) para a API de formatação do Sheets.
PMO_TUTOR_NAME_COLUMN_INDEX = 0
_PMO_ROUTE_COORDS_CACHE: dict[str, tuple[float, float]] = {}

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

# ——— Criação do "dia de vacinação" ————————————————————————————————————————
# Aba modelo que é duplicada a cada novo dia e aba de onde saem as casas a agendar.
PMO_TEMPLATE_SHEET_TITLE_ENV = "PMO_VACCINE_TEMPLATE_SHEET_TITLE"
PMO_TEMPLATE_SHEET_DEFAULT_TITLE = "padrão"
PMO_SCHEDULE_SOURCE_SHEET_TITLE_ENV = "PMO_VACCINE_SCHEDULE_SOURCE_SHEET_TITLE"
PMO_SCHEDULE_SOURCE_SHEET_DEFAULT_TITLE = "Inscrição a agendar"

# Célula-mestra (verde) onde a data do dia é gravada na aba nova.
PMO_DATE_MASTER_CELL = "Q13"
# Colunas copiadas de cada casa (A..K) da "inscrições a agendar" para a aba do dia.
PMO_SCHEDULE_SOURCE_COLUMNS = 11  # A..K

# Metas de distribuição por turno. O número de ANIMAIS manda (alvo ~22-23, teto 24);
# as casas são flexíveis, limitadas só pelas 9 linhas de cada turno no modelo.
PMO_DAY_TARGET_ANIMALS = 23      # alvo do dia (faixa boa 22-23)
PMO_DAY_MAX_ANIMALS = 24         # teto duro: casas avulsas nunca passam disso
PMO_MORNING_TARGET_ANIMALS = 13  # manhã pega um pouco mais que metade
PMO_MORNING_MAX_HOUSES = 9
PMO_AFTERNOON_MAX_HOUSES = 7

# Cores de marcação das casas já agendadas (linha inteira), uma por turno.
PMO_SCHEDULE_COLORS: dict[str, dict[str, float]] = {
    "Manha": {"red": 0.851, "green": 0.918, "blue": 0.827},  # verde claro
    "Tarde": {"red": 0.812, "green": 0.886, "blue": 0.953},  # azul claro
}
# Acima desse valor em todos os canais consideramos a célula "sem cor" (branca).
PMO_SCHEDULE_WHITE_THRESHOLD = 0.93


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


def _first_access_url() -> str:
    if has_request_context():
        return url_for("first_access", _external=True)
    return "/primeiro-acesso"


def _parse_date(value: Any) -> str:
    text = _normalize_text(value)
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
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


def _pmo_is_master_sheet(title: Any) -> bool:
    """True quando o título é a aba mestre de status — o app não deve escrever nela."""
    def _norm(value: Any) -> str:
        return re.sub(r"\s+", " ", _strip_accents(_normalize_text(value)).lower()).strip()

    return bool(_normalize_text(title)) and _norm(title) == _norm(PMO_MASTER_SHEET_TITLE)


def _pmo_address_parts(address: str) -> dict[str, str]:
    parts = [_normalize_text(part) for part in str(address or "").split(",") if _normalize_text(part)]
    return {
        "rua": parts[0] if len(parts) > 0 else "",
        "numero": parts[1] if len(parts) > 1 else "",
        "complemento": parts[2] if len(parts) > 2 else "",
        "bairro": parts[-1] if len(parts) > 3 else (parts[2] if len(parts) == 3 else ""),
    }


def _pmo_clean_address_fragment(value: str) -> str:
    text = _normalize_text(value)
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b(antigo|nova|novo)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+-\s+", " ", text)
    text = re.sub(r"\bR\.\s*", "Rua ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bAv\.\s*", "Avenida ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bAl\.\s*", "Alameda ", text, flags=re.IGNORECASE)
    return _normalize_text(text)


def _pmo_unique_queries(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        normalized = _normalize_text(query)
        if not normalized:
            continue
        key = _strip_accents(normalized).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


def _pmo_route_geocode_variants() -> int:
    try:
        return max(1, int(os.getenv(PMO_ROUTE_GEOCODE_VARIANTS_ENV, "5")))
    except ValueError:
        return 5


def _pmo_address_queries(address: str) -> list[str]:
    normalized = _pmo_clean_address_fragment(address)
    parts = _pmo_address_parts(normalized)
    street = _pmo_clean_address_fragment(parts["rua"])
    number = _pmo_clean_address_fragment(parts["numero"])
    neighborhood = _pmo_clean_address_fragment(parts["bairro"])
    street_no_number = _normalize_text(re.sub(r"\b\d+[A-Za-z]?\b", " ", street))
    city = "Orlândia, SP, Brasil"
    return _pmo_unique_queries([
        f"{normalized}, {city}",
        ", ".join(part for part in (street, number, neighborhood, city) if part),
        ", ".join(part for part in (street, number, city) if part),
        ", ".join(part for part in (street_no_number, number, neighborhood, city) if part),
        ", ".join(part for part in (street_no_number, neighborhood, city) if part),
        ", ".join(part for part in (street, neighborhood, city) if part),
        ", ".join(part for part in (neighborhood, city) if part),
    ])


def _pmo_coords_in_orlandia(coords: tuple[float, float]) -> bool:
    lat, lng = coords
    return (
        PMO_ORLANDIA_BOUNDS["min_lat"] <= lat <= PMO_ORLANDIA_BOUNDS["max_lat"]
        and PMO_ORLANDIA_BOUNDS["min_lng"] <= lng <= PMO_ORLANDIA_BOUNDS["max_lng"]
    )


def _pmo_extract_best_nominatim_coords(payload: list[dict[str, Any]]) -> tuple[float, float] | None:
    for item in payload:
        try:
            coords = float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        display = _strip_accents(str(item.get("display_name") or "")).lower()
        if "orlandia" in display and _pmo_coords_in_orlandia(coords):
            return coords
    for item in payload:
        try:
            coords = float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if _pmo_coords_in_orlandia(coords):
            return coords
    return None


def _pmo_geocode_address(address: str) -> tuple[float, float] | None:
    """Geocode a free-text PMO address.

    Tries helpers.geocode_address (structured Nominatim, 5 s timeout) first,
    then falls back to PMO-specific free-text queries.
    """
    normalized = _normalize_text(address)
    if not normalized:
        return None
    cache_key = _strip_accents(normalized).lower()
    if cache_key in _PMO_ROUTE_COORDS_CACHE:
        return _PMO_ROUTE_COORDS_CACHE[cache_key]

    parts = _pmo_address_parts(normalized)
    rua = _pmo_clean_address_fragment(parts["rua"])
    numero = _pmo_clean_address_fragment(parts["numero"])
    bairro = _pmo_clean_address_fragment(parts["bairro"])

    # Structured search via helpers (better Nominatim structured params, 5 s timeout)
    try:
        from helpers import geocode_address as _geocode_helper
        coords = _geocode_helper(rua=rua, numero=numero, bairro=bairro, cidade="Orlândia", estado="SP")
    except Exception:
        coords = None

    if coords and _pmo_coords_in_orlandia(coords):
        _PMO_ROUTE_COORDS_CACHE[cache_key] = coords
        return coords

    # Free-text Nominatim fallback with longer timeout
    http = requests.Session()
    http.headers.update({"User-Agent": "PetOrlandia/1.0 (+https://petorlandia.com)"})
    for query in _pmo_address_queries(normalized)[:_pmo_route_geocode_variants()]:
        try:
            response = http.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 3, "countrycodes": "br"},
                timeout=5,
            )
            response.raise_for_status()
            coords = _pmo_extract_best_nominatim_coords(response.json() or [])
        except (requests.RequestException, ValueError):
            coords = None
        if coords:
            _PMO_ROUTE_COORDS_CACHE[cache_key] = coords
            return coords
    return None


def _pmo_geocode_visit(visit: PmoVaccinationVisit) -> tuple[float, float] | None:
    """Return coordinates for a visit, using DB-persisted cache when available.

    The DB cache survives Heroku dyno restarts.  The in-memory dict avoids
    redundant DB reads within the same request.
    """
    address = visit.address or ""
    cache_key = _strip_accents(_normalize_text(address)).lower()
    if not cache_key:
        return None

    # 1. In-memory cache (fast within a dyno)
    if cache_key in _PMO_ROUTE_COORDS_CACHE:
        return _PMO_ROUTE_COORDS_CACHE[cache_key]

    # 2. DB-persisted cache (survives restarts)
    if (
        visit.geocode_lat is not None
        and visit.geocode_lng is not None
        and visit.geocode_address_key == cache_key
    ):
        coords: tuple[float, float] = (visit.geocode_lat, visit.geocode_lng)
        _PMO_ROUTE_COORDS_CACHE[cache_key] = coords
        return coords

    # 3. Fresh geocode
    coords = _pmo_geocode_address(address)
    if coords:
        visit.geocode_lat = coords[0]
        visit.geocode_lng = coords[1]
        visit.geocode_address_key = cache_key
    return coords


def _pmo_route_geocode_limit() -> int:
    try:
        return max(0, int(os.getenv(PMO_ROUTE_GEOCODE_LIMIT_ENV, "18")))
    except ValueError:
        return 18


def _pmo_route_origin_address() -> str:
    return _normalize_text(os.getenv(PMO_ROUTE_ORIGIN_ADDRESS_ENV)) or PMO_DEFAULT_ROUTE_ORIGIN_ADDRESS


def _pmo_route_origin_coords() -> tuple[float, float] | None:
    try:
        lat = float(os.getenv(PMO_ROUTE_ORIGIN_LAT_ENV, ""))
        lng = float(os.getenv(PMO_ROUTE_ORIGIN_LNG_ENV, ""))
        return lat, lng
    except ValueError:
        return PMO_DEFAULT_ROUTE_ORIGIN_COORDS


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
    if _parse_date_object(first) and len(values) > 1:
        first = values[1]
    if not re.search(r"[a-zA-ZÀ-ú]", first):
        return True
    return any(
        marker in joined
        for marker in (
            "nome completo do tutor",
            "total de animais",
            "digite o dia",
            "doses utilizadas",
            "cachorros:",
            "gatos:",
            "column 1",
            "perdas",
            "sobras",
        )
    )


# Separadores que delimitam animais diferentes: vírgula, ponto e vírgula, quebra
# de linha e a conjunção " e ".  Cada um deve ser IGNORADO quando aparece dentro de
# parênteses, pois os tutores escrevem descrições como "Branca (mais nova e braba)" —
# sem isso o "e"/vírgula da descrição quebra um nome em vários animais fantasmas.
_ANIMAL_SEPARATOR_RE = re.compile(r",|;|\n|\se\s", re.IGNORECASE)


def _split_animals(value: Any) -> list[str]:
    text = _normalize_text(value)
    if not text:
        return []
    parts: list[str] = []
    depth = 0
    start = 0
    i = 0
    while i < len(text):
        char = text[i]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0:
            match = _ANIMAL_SEPARATOR_RE.match(text, i)
            if match:
                parts.append(text[start:i])
                i = match.end()
                start = i
                continue
        i += 1
    parts.append(text[start:])
    return [_normalize_text(part) for part in parts if _normalize_text(part)]


def _build_animals(names: list[str], dogs: int, cats: int) -> list[dict[str, str]]:
    # As quantidades de cães/gatos vêm de colunas próprias da planilha e são a
    # contagem AUTORITATIVA de animais. Só usamos o número de nomes encontrados no
    # texto livre quando nenhuma quantidade foi informada — assim uma descrição
    # bagunçada nunca infla a contagem de animais (o que deixaria pets fantasmas
    # presos em "pendente" e marcaria a visita inteira como "parcial").
    count = dogs + cats
    total = count if count > 0 else len(names)
    animals: list[dict[str, str]] = []
    for index in range(total):
        species = "cao" if index < dogs else "gato"
        fallback = f"Cao {index + 1}" if species == "cao" else f"Gato {index - dogs + 1}"
        animals.append(
            {
                "name": (names[index] if index < len(names) else fallback)[:PMO_ANIMAL_NAME_MAX],
                "species": species,
                "status": "pendente",
            }
        )
    return animals


def _cell(row: list[Any], index: int) -> str:
    return _normalize_text(row[index]) if len(row) > index else ""


def _row_column_offset(row: list[Any]) -> int:
    return 1 if _parse_date_object(_cell(row, 0)) and _cell(row, 1) else 0


def _password(seed: str) -> str:
    suffix = (_digits(seed)[-4:] or "0000").rjust(4, "0")
    letter = secrets.choice(string.ascii_uppercase.replace("I", "").replace("O", ""))
    return f"PMO{letter}{suffix}"


def _public_token() -> str:
    return secrets.token_urlsafe(32)


def _provisional_email(phone: str, visit_id: int | None = None) -> str:
    digits = _digits(phone)[-13:] or str(visit_id or secrets.randbelow(999999)).zfill(6)
    return f"pmo-{digits}@petorlandia.local"


def _normalize_person_name(value: Any) -> str:
    return re.sub(r"\s+", " ", _strip_accents(_normalize_text(value)).lower()).strip()


def _find_user_by_phone(phone: str) -> User | None:
    normalized = _normalize_login_phone(phone)
    if not normalized:
        return None
    for user in User.query.filter(User.phone.isnot(None), User.phone != "").all():
        if _normalize_login_phone(user.phone) == normalized:
            return user
    return None


def _find_user_by_phone_and_name(phone: str, name: str) -> User | None:
    """Reusa uma conta apenas quando telefone E nome batem.

    Evita misturar famílias diferentes que compartilham o mesmo telefone na
    planilha (ex.: telefone de um agente de saúde repetido em várias linhas).
    """
    normalized = _normalize_login_phone(phone)
    if not normalized:
        return None
    target_name = _normalize_person_name(name)
    for user in User.query.filter(User.phone.isnot(None), User.phone != "").all():
        if _normalize_login_phone(user.phone) != normalized:
            continue
        if _normalize_person_name(user.name) == target_name:
            return user
    return None


def _same_family(user: User | None, visit: PmoVaccinationVisit) -> bool:
    if not user:
        return False
    phone = visit.phone1 or visit.phone2
    if _normalize_login_phone(user.phone) != _normalize_login_phone(phone):
        return False
    return _normalize_person_name(user.name) == _normalize_person_name(visit.tutor_name)


def _unique_provisional_email(normalized_phone: str, visit: PmoVaccinationVisit) -> str:
    candidate = _provisional_email(normalized_phone, visit.id)
    if not User.query.filter(func.lower(User.email) == candidate.lower()).first():
        return candidate
    # Telefone compartilhado entre famílias: garante e-mail único por visita.
    digits = _digits(normalized_phone)[-13:] or "x"
    suffix = visit.id or secrets.token_hex(4)
    return f"pmo-{digits}-{suffix}@petorlandia.local"


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
    normalized_phone = _normalize_login_phone(phone)
    if not normalized_phone:
        return
    # Só reaproveita uma conta existente quando telefone E nome conferem; caso
    # contrário cria conta separada (evita juntar famílias que dividem telefone).
    user = _find_user_by_phone_and_name(phone, visit.tutor_name)
    if user:
        visit.tutor_user = user
        if visit.address and not user.address:
            user.address = visit.address
        return
    user = User(
        name=visit.tutor_name,
        email=_unique_provisional_email(normalized_phone, visit),
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
        name=(pmo_animal.name or "")[:PMO_ANIMAL_NAME_MAX],
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


def ensure_vacina_pmo_real_animal(animal_id: int) -> Animal | None:
    """Garante que o ``PmoVaccinationAnimal`` tenha um ``Animal`` real vinculado.

    Usado para guardar a foto tirada pelo vacinador no cadastro do animal.
    Retorna o ``Animal`` (criando/vinculando quando possível) ou ``None`` quando
    não há tutor para vincular o cadastro.
    """
    pmo_animal = PmoVaccinationAnimal.query.get_or_404(animal_id)
    _ensure_real_animal(pmo_animal)
    db.session.flush()
    if not pmo_animal.animal_id:
        return None
    return db.session.get(Animal, pmo_animal.animal_id)


def repair_pmo_tutor_links(dry_run: bool = True) -> dict:
    """Corrige perfis PMO que receberam animais de outras famílias.

    Causa: contas de tutor eram reaproveitadas só pelo telefone; quando a
    planilha repete o telefone em famílias diferentes, os animais de todas elas
    foram parar no mesmo usuário. Esta rotina reatribui cada animal real criado
    pelo PMO ao tutor correto da sua visita (chave telefone+nome), criando as
    contas por família que faltarem.

    Em ``dry_run`` apenas conta o que seria alterado, sem gravar nada.
    """
    stats = {
        "visitas_com_animais": 0,
        "animais_reatribuidos": 0,
        "contas_criadas": 0,
        "visitas_revinculadas": 0,
    }
    visits = PmoVaccinationVisit.query.all()
    for visit in visits:
        linked = [pa for pa in visit.animals if pa.animal_id]
        if not linked:
            continue
        stats["visitas_com_animais"] += 1

        misattached = []
        for pmo_animal in linked:
            animal = db.session.get(Animal, pmo_animal.animal_id)
            if animal is None:
                continue
            owner = db.session.get(User, animal.user_id) if animal.user_id else None
            if _same_family(owner, visit):
                continue  # já está no tutor correto
            misattached.append(animal)

        owner_needs_fix = not _same_family(
            db.session.get(User, visit.tutor_user_id) if visit.tutor_user_id else None,
            visit,
        )
        if not misattached and not owner_needs_fix:
            continue

        if dry_run:
            stats["animais_reatribuidos"] += len(misattached)
            if owner_needs_fix:
                stats["visitas_revinculadas"] += 1
                if _find_user_by_phone_and_name(visit.phone1 or visit.phone2, visit.tutor_name) is None:
                    stats["contas_criadas"] += 1
            continue

        target = _find_user_by_phone_and_name(visit.phone1 or visit.phone2, visit.tutor_name)
        if target is None:
            normalized_phone = _normalize_login_phone(visit.phone1 or visit.phone2)
            if not normalized_phone:
                continue
            target = User(
                name=visit.tutor_name,
                email=_unique_provisional_email(normalized_phone, visit),
                phone=normalized_phone,
                role="adotante",
                address=visit.address or None,
            )
            target.set_password(visit.password)
            db.session.add(target)
            db.session.flush()
            stats["contas_criadas"] += 1

        for animal in misattached:
            animal.user_id = target.id
            stats["animais_reatribuidos"] += 1
        if visit.tutor_user_id != target.id:
            visit.tutor_user_id = target.id
            stats["visitas_revinculadas"] += 1

    if not dry_run:
        db.session.commit()
    return stats


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


def _visit_identity_changed(
    visit: PmoVaccinationVisit,
    *,
    tutor_name: str,
    phone1: str,
    phone2: str,
) -> bool:
    old_phones = {
        _normalize_login_phone(value)
        for value in (visit.phone1, visit.phone2)
        if _normalize_login_phone(value)
    }
    new_phones = {
        _normalize_login_phone(value)
        for value in (phone1, phone2)
        if _normalize_login_phone(value)
    }
    if old_phones and new_phones:
        return old_phones.isdisjoint(new_phones)
    old_name = _strip_accents(visit.tutor_name or "").casefold().strip()
    new_name = _strip_accents(tutor_name or "").casefold().strip()
    return bool(old_name and new_name and old_name != new_name)


def _pmo_animal_identity_changed(
    animal: PmoVaccinationAnimal,
    *,
    name: str,
    species: str,
) -> bool:
    old_name = _strip_accents(animal.name or "").casefold().strip()
    new_name = _strip_accents(name or "").casefold().strip()
    return bool(old_name and new_name and old_name != new_name) or animal.species != species


def _clear_pmo_animal_links(animal: PmoVaccinationAnimal) -> None:
    animal.animal_id = None
    animal.vaccine_id = None
    animal.vaccinated_at = None


def parse_vacina_pmo_rows(values: list[list[Any]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for index, row in enumerate(values):
        if _is_summary_or_header(row):
            continue

        offset = _row_column_offset(row)
        requested_date = _parse_date(_cell(row, 0)) if offset else None
        tutor = _cell(row, 0 + offset)
        phone1 = _normalize_phone(_cell(row, 5 + offset))
        phone2 = _normalize_phone(_cell(row, 6 + offset))
        dogs = _parse_count(_cell(row, 7 + offset))
        cats = _parse_count(_cell(row, 8 + offset))
        animals = _build_animals(_split_animals(_cell(row, 9 + offset)), dogs, cats)
        address = ", ".join(
            item
            for item in (
                _cell(row, 1 + offset),
                _cell(row, 2 + offset),
                _cell(row, 3 + offset),
                _cell(row, 4 + offset),
            )
            if item
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
                "note": _cell(row, 10 + offset),
                "requestedDate": requested_date,
                "date": _parse_date(_cell(row, 16 + offset) or _cell(row, 11 + offset)),
                "shift": _normalize_shift(_cell(row, 17 + offset)),
                "password": _password(phone1 or phone2 or str(index)),
                "certificateUrl": "",
                "sourceRow": index + 1,
                "attendedBy": _cell(row, 14 + offset),
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
        "requestedDate": visit.requested_date.isoformat() if visit.requested_date else "",
        "date": visit.vaccine_date.isoformat() if visit.vaccine_date else "",
        "shift": visit.shift or "",
        "password": visit.password,
        "loginPhone": format_pmo_phone_for_login(visit.phone1 or visit.phone2),
        "certificateUrl": visit.certificate_url or public_url,
        "publicUrl": public_url,
        "firstAccessUrl": _first_access_url(),
        "attendedBy": visit.attended_by or "",
        "losses": visit.losses or 0,
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


def _route_preview_item(visit: PmoVaccinationVisit, coords: tuple[float, float] | None, order: int) -> dict[str, Any]:
    return {
        "visitId": visit.id,
        "sourceRow": visit.source_row,
        "order": order,
        "tutor": visit.tutor_name or "",
        "address": visit.address or "",
        "shift": visit.shift or "",
        "located": bool(coords),
    }


def _sync_visit_source_rows_after_route(
    *,
    spreadsheet_id: str,
    sheet_gid: str,
    sheet_title: str,
    assignments: list[tuple[PmoVaccinationVisit, int]],
) -> None:
    for visit, _row in assignments:
        visit.source_row = -visit.id
    db.session.flush()
    for visit, source_row in assignments:
        visit.source_row = source_row
        visit.sheet_title = sheet_title
        visit.sheet_gid = sheet_gid
        visit.spreadsheet_id = spreadsheet_id
    db.session.commit()


def _pmo_route_context(*, sheet_gid: str = "", sheet_title: str = "", shift: str = "") -> dict[str, Any]:
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
    spreadsheet_id = visits[0].spreadsheet_id if visits else ""
    resolved_gid = sheet_gid or (visits[0].sheet_gid if visits else "")
    resolved_title = sheet_title or (visits[0].sheet_title if visits else "")
    if not spreadsheet_id or not resolved_title:
        raise ValueError("Sincronize a aba antes de otimizar a rota.")

    service = _get_sheets_service_rw()
    range_value = f"{_quote_sheet_title(resolved_title)}!A:R"
    response = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_value)
        .execute()
    )
    sheet_values = response.get("values", [])
    parsed_rows_by_source = {
        int(row["sourceRow"]): row
        for row in parse_vacina_pmo_rows(sheet_values)
        if int(row.get("sourceRow") or 0) > 0
    }
    selected = [
        visit
        for visit in visits
        if visit.source_row
        and visit.source_row > 1
        and visit.source_row in parsed_rows_by_source
        and _normalize_shift(parsed_rows_by_source[visit.source_row].get("shift")) == normalized_shift
    ]
    if len(selected) < 2:
        raise ValueError("Este turno precisa de pelo menos dois endereços sincronizados para otimizar.")

    origin_coords = _pmo_route_origin_coords()
    if not origin_coords:
        raise ValueError("Não foi possível localizar a Vigilância Sanitária de Orlândia para iniciar a rota.")

    target_rows = sorted(visit.source_row for visit in selected if visit.source_row)
    needed_rows = max(target_rows)
    while len(sheet_values) < needed_rows:
        sheet_values.append([])

    geocoded: list[tuple[PmoVaccinationVisit, tuple[float, float]]] = []
    ungeocoded: list[PmoVaccinationVisit] = []
    geocoded_now = 0
    geocode_limit = _pmo_route_geocode_limit()
    for visit in selected:
        coords = None
        # Always use DB cache even beyond the fresh-geocode limit
        cache_key = _strip_accents(_normalize_text(visit.address or "")).lower()
        if cache_key and (
            cache_key in _PMO_ROUTE_COORDS_CACHE
            or (
                visit.geocode_lat is not None
                and visit.geocode_lng is not None
                and visit.geocode_address_key == cache_key
            )
        ):
            coords = _pmo_geocode_visit(visit)
        elif geocoded_now < geocode_limit:
            coords = _pmo_geocode_visit(visit)
            geocoded_now += 1
        if coords:
            geocoded.append((visit, coords))
        else:
            ungeocoded.append(visit)
    # Persist any newly geocoded coordinates before heavy Sheets work
    try:
        db.session.flush()
    except Exception:
        pass
    if not geocoded:
        raise ValueError(
            "Não foi possível localizar nenhum endereço deste turno rapidamente. "
            "Confira se os endereços têm rua, número e bairro, e tente novamente em alguns instantes."
        )

    optimized = _nearest_neighbor_route(origin_coords, geocoded) + ungeocoded
    return {
        "normalized_shift": normalized_shift,
        "spreadsheet_id": spreadsheet_id,
        "sheet_gid": resolved_gid,
        "sheet_title": resolved_title,
        "service": service,
        "sheet_values": sheet_values,
        "selected": selected,
        "target_rows": target_rows,
        "optimized": optimized,
        "coords_by_visit_id": {visit.id: coords for visit, coords in geocoded},
        "unlocated_count": len(ungeocoded),
        "geocoded_now": geocoded_now,
    }


def preview_vacina_pmo_route(*, sheet_gid: str = "", sheet_title: str = "", shift: str = "") -> dict[str, Any]:
    context = _pmo_route_context(sheet_gid=sheet_gid, sheet_title=sheet_title, shift=shift)
    coords_by_visit_id = context["coords_by_visit_id"]
    return {
        "sheet_gid": context["sheet_gid"],
        "sheet_title": context["sheet_title"],
        "spreadsheet_id": context["spreadsheet_id"],
        "shift": context["normalized_shift"],
        "origin": _pmo_route_origin_address(),
        "optimized_count": len(context["optimized"]),
        "unlocated_count": context["unlocated_count"],
        "geocoded_now": context["geocoded_now"],
        "preview": [
            _route_preview_item(visit, coords_by_visit_id.get(visit.id), index)
            for index, visit in enumerate(context["optimized"], start=1)
        ],
    }


def optimize_vacina_pmo_route(
    *,
    sheet_gid: str = "",
    sheet_title: str = "",
    shift: str = "",
    created_by_id: int | None = None,
) -> dict[str, Any]:
    context = _pmo_route_context(sheet_gid=sheet_gid, sheet_title=sheet_title, shift=shift)
    spreadsheet_id = context["spreadsheet_id"]
    resolved_gid = context["sheet_gid"]
    resolved_title = context["sheet_title"]
    service = context["service"]
    sheet_values = context["sheet_values"]
    selected = context["selected"]
    target_rows = context["target_rows"]
    optimized = context["optimized"]

    source_rows_by_visit_id = {
        visit.id: list(sheet_values[(visit.source_row or 1) - 1])
        for visit in selected
    }
    before_values = [list(sheet_values[row - 1]) for row in target_rows]
    for destination_row, visit in zip(target_rows, optimized):
        sheet_values[destination_row - 1] = source_rows_by_visit_id.get(visit.id, [])
    after_values = [list(sheet_values[row - 1]) for row in target_rows]

    backup = PmoRouteOptimizationBackup(
        spreadsheet_id=spreadsheet_id,
        sheet_gid=resolved_gid,
        sheet_title=resolved_title,
        shift=context["normalized_shift"],
        source_rows_json=json.dumps(target_rows, ensure_ascii=False),
        before_values_json=json.dumps(before_values, ensure_ascii=False),
        after_values_json=json.dumps(after_values, ensure_ascii=False),
        created_by_id=created_by_id,
    )
    db.session.add(backup)
    db.session.flush()

    for destination_row in target_rows:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet_title(resolved_title)}!A{destination_row}:R{destination_row}",
            valueInputOption="USER_ENTERED",
            body={"values": [sheet_values[destination_row - 1]]},
        ).execute()

    _sync_visit_source_rows_after_route(
        spreadsheet_id=spreadsheet_id,
        sheet_gid=resolved_gid,
        sheet_title=resolved_title,
        assignments=list(zip(optimized, target_rows)),
    )

    state = get_saved_vacina_pmo_rows(sheet_gid=resolved_gid, sheet_title=resolved_title)
    return {
        **state,
        "shift": context["normalized_shift"],
        "origin": _pmo_route_origin_address(),
        "optimized_count": len(optimized),
        "unlocated_count": context["unlocated_count"],
        "geocoded_now": context["geocoded_now"],
        "backup_id": backup.id,
    }


def undo_last_vacina_pmo_route_optimization(*, sheet_gid: str = "", sheet_title: str = "", shift: str = "") -> dict[str, Any]:
    normalized_shift = _normalize_shift(shift)
    query = PmoRouteOptimizationBackup.query.filter(PmoRouteOptimizationBackup.undone_at.is_(None))
    if sheet_gid:
        query = query.filter(PmoRouteOptimizationBackup.sheet_gid == sheet_gid)
    if sheet_title:
        query = query.filter(PmoRouteOptimizationBackup.sheet_title == sheet_title)
    if normalized_shift:
        query = query.filter(PmoRouteOptimizationBackup.shift == normalized_shift)
    backup = query.order_by(PmoRouteOptimizationBackup.created_at.desc(), PmoRouteOptimizationBackup.id.desc()).first()
    if not backup:
        raise ValueError("Não há otimização recente para desfazer neste turno.")

    source_rows = json.loads(backup.source_rows_json)
    before_values = json.loads(backup.before_values_json)
    service = _get_sheets_service_rw()
    for source_row, row_values in zip(source_rows, before_values):
        service.spreadsheets().values().update(
            spreadsheetId=backup.spreadsheet_id,
            range=f"{_quote_sheet_title(backup.sheet_title)}!A{source_row}:R{source_row}",
            valueInputOption="USER_ENTERED",
            body={"values": [row_values]},
        ).execute()

    parsed_by_source = {
        int(row["sourceRow"]): row
        for row in parse_vacina_pmo_rows(before_values)
        if int(row.get("sourceRow") or 0) > 0
    }
    assignments: list[tuple[PmoVaccinationVisit, int]] = []
    candidates = (
        _query_sheet_visits(sheet_gid=backup.sheet_gid, sheet_title=backup.sheet_title, spreadsheet_id=backup.spreadsheet_id)
        .all()
    )
    for offset, source_row in enumerate(source_rows):
        row_values = before_values[offset]
        parsed = parse_vacina_pmo_rows([row_values])
        if not parsed:
            continue
        row = parsed[0]
        match = next(
            (
                visit for visit in candidates
                if _normalize_text(visit.tutor_name) == _normalize_text(row.get("tutor"))
                and _normalize_text(visit.address) == _normalize_text(row.get("address"))
            ),
            None,
        )
        if match:
            assignments.append((match, int(source_row)))
    if assignments:
        _sync_visit_source_rows_after_route(
            spreadsheet_id=backup.spreadsheet_id,
            sheet_gid=backup.sheet_gid,
            sheet_title=backup.sheet_title,
            assignments=assignments,
        )

    backup.undone_at = utcnow()
    db.session.commit()
    state = get_saved_vacina_pmo_rows(sheet_gid=backup.sheet_gid, sheet_title=backup.sheet_title)
    return {
        **state,
        "shift": backup.shift,
        "undone_backup_id": backup.id,
    }


def persist_vacina_pmo_rows(
    rows: list[dict[str, Any]],
    *,
    spreadsheet_id: str,
    sheet_gid: str,
    sheet_title: str,
    prune_orphans: bool = False,
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

        tutor_name = row.get("tutor") or ""
        phone1 = row.get("phone1") or ""
        phone2 = row.get("phone2") or ""
        if visit.id and _visit_identity_changed(
            visit,
            tutor_name=tutor_name,
            phone1=phone1,
            phone2=phone2,
        ):
            visit.tutor_user_id = None
            for pmo_animal in visit.animals:
                _clear_pmo_animal_links(pmo_animal)

        visit.sheet_title = sheet_title
        visit.tutor_name = tutor_name
        new_address = row.get("address") or ""
        if _strip_accents(_normalize_text(new_address)).lower() != _strip_accents(_normalize_text(visit.address or "")).lower():
            visit.geocode_lat = None
            visit.geocode_lng = None
            visit.geocode_address_key = None
        visit.address = new_address
        visit.phone1 = phone1
        visit.phone2 = phone2
        visit.dogs = int(row.get("dogs") or 0)
        visit.cats = int(row.get("cats") or 0)
        visit.requested_date = _parse_date_object(row.get("requestedDate"))
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
            name = (animal_data.get("name") or f"Animal {position}")[:PMO_ANIMAL_NAME_MAX]
            species = animal_data.get("species") or "cao"
            if not animal:
                animal = PmoVaccinationAnimal(
                    visit=visit,
                    position=position,
                    status=animal_data.get("status") or "pendente",
                )
                db.session.add(animal)
            elif _pmo_animal_identity_changed(animal, name=name, species=species):
                _clear_pmo_animal_links(animal)
            animal.name = name
            animal.species = species
            keep_positions.add(position)

        for position, animal in list(existing_by_position.items()):
            if position not in keep_positions:
                db.session.delete(animal)

        _ensure_visit_records(visit)

        saved.append(visit)

    # Remove registros órfãos: linhas que existiam no banco para esta aba mas
    # não aparecem mais na planilha (ex.: tutor removido da lista do dia).
    # Só roda quando solicitado e nunca na aba mestre, para não apagar o
    # histórico compilado do Status PMO.
    if prune_orphans and sheet_gid and not _pmo_is_master_sheet(sheet_title):
        live_rows = {
            int(row.get("sourceRow") or 0)
            for row in rows
            if int(row.get("sourceRow") or 0) > 0
        }
        if live_rows:  # só limpa se o sync retornou dados; evita apagar tudo em caso de falha
            stale = (
                PmoVaccinationVisit.query
                .filter_by(spreadsheet_id=spreadsheet_id, sheet_gid=sheet_gid)
                .filter(PmoVaccinationVisit.source_row.notin_(live_rows))
                .all()
            )
            for stale_visit in stale:
                db.session.delete(stale_visit)

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
    if _pmo_is_master_sheet(visit.sheet_title):
        return False  # nunca escreve na aba mestre (coluna M = Status PMO compilado)

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
    if _pmo_is_master_sheet(visit.sheet_title):
        return False  # nunca escreve na aba mestre

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
    if _pmo_is_master_sheet(visit.sheet_title):
        return False  # nunca pinta a aba mestre (coluna A é gerida pelo status-sync)
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


def write_animal_names_to_sheet(visit: PmoVaccinationVisit) -> bool:
    """Escreve os nomes dos animais (coluna J) na linha de origem do tutor."""
    if not visit.spreadsheet_id or not visit.source_row:
        return False
    if not visit.sheet_title and not visit.sheet_gid:
        return False
    if _pmo_is_master_sheet(visit.sheet_title):
        return False  # nunca escreve na aba mestre

    names = ", ".join(animal.name for animal in visit.animals if animal.name)

    try:
        service = _get_sheets_service_rw()
    except Exception:
        from flask import current_app
        try:
            current_app.logger.warning(
                "Falha ao iniciar cliente Sheets para gravar nomes de animais PMO", exc_info=True
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
        range_value = f"{_quote_sheet_title(title)}!{PMO_ANIMAL_NAMES_COLUMN}{visit.source_row}"
        service.spreadsheets().values().update(
            spreadsheetId=visit.spreadsheet_id,
            range=range_value,
            valueInputOption="USER_ENTERED",
            body={"values": [[names]]},
        ).execute()
        return True
    except Exception:
        from flask import current_app
        try:
            current_app.logger.warning(
                "Falha ao atualizar nomes de animais na planilha PMO", exc_info=True
            )
        except Exception:
            pass
        return False


def update_vacina_pmo_animal_name(animal_id: int, name: str) -> dict[str, Any]:
    """Corrige o nome de um animal e replica a célula de nomes (coluna J) na planilha."""
    normalized = _normalize_text(name)
    if not normalized:
        raise ValueError("Digite o nome do animal.")
    if len(normalized) > PMO_ANIMAL_NAME_MAX:
        raise ValueError(f"O nome do animal deve ter no máximo {PMO_ANIMAL_NAME_MAX} caracteres.")
    # A célula da planilha é reimportada separando por vírgula/";"/" e "; um nome com
    # esses separadores viraria dois animais na próxima sincronização.
    if len(_split_animals(normalized)) > 1:
        raise ValueError("Use um nome sem vírgulas, ponto e vírgula ou \" e \" — ele separa animais na planilha.")

    animal = PmoVaccinationAnimal.query.get_or_404(animal_id)
    old_name = animal.name or ""
    if normalized == old_name:
        return _serialize_visit(animal.visit)

    # Se o cadastro real ainda carrega o nome antigo (criado automaticamente pela
    # campanha), renomeia junto para manter carteirinha e certificado coerentes.
    if animal.animal_id:
        real = db.session.get(Animal, animal.animal_id)
        if real and _strip_accents(real.name or "").casefold().strip() == _strip_accents(old_name).casefold().strip():
            real.name = normalized
    animal.name = normalized
    db.session.commit()
    write_animal_names_to_sheet(animal.visit)
    return _serialize_visit(animal.visit)


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
    # Sem nome digitado, a coluna O recebe o tutor do cadastro assim que a
    # visita ganha um desfecho presencial (ver _attended_by_sheet_value).
    write_attended_by_to_sheet(animal.visit)
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


def _attended_by_sheet_value(visit: PmoVaccinationVisit) -> str:
    """Valor da coluna O: nome digitado ou, se vazio, o próprio tutor do cadastro.

    O fallback só vale quando alguém de fato atendeu a porta (algum animal com
    desfecho presencial); visita só com pendente/ausente deixa a célula em branco.
    """
    if visit.attended_by:
        return visit.attended_by
    attended_statuses = {"vacinado", "recusou", "remarcar"}
    if any((animal.status or "") in attended_statuses for animal in visit.animals):
        return visit.tutor_name or ""
    return ""


def write_attended_by_to_sheet(visit: PmoVaccinationVisit) -> bool:
    """Escreve o nome de quem atendeu (coluna O) na linha de origem do tutor."""
    if not visit.spreadsheet_id or not visit.source_row:
        return False
    if not visit.sheet_title and not visit.sheet_gid:
        return False
    if _pmo_is_master_sheet(visit.sheet_title):
        return False  # nunca escreve na aba mestre

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
            body={"values": [[_attended_by_sheet_value(visit)]]},
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


PMO_VISIT_LOSSES_MAX = 30


def update_vacina_pmo_visit_losses(visit_id: int, losses: Any) -> dict[str, Any]:
    """Registra as doses perdidas na visita e deixa rastro na observação (coluna K)."""
    visit = PmoVaccinationVisit.query.get_or_404(visit_id)
    try:
        value = int(losses)
    except (TypeError, ValueError):
        raise ValueError(f"Informe um número de perdas entre 0 e {PMO_VISIT_LOSSES_MAX}.")
    if value < 0 or value > PMO_VISIT_LOSSES_MAX:
        raise ValueError(f"Informe um número de perdas entre 0 e {PMO_VISIT_LOSSES_MAX}.")
    if value == (visit.losses or 0):
        return _serialize_visit(visit)
    visit.losses = value
    label = "dose perdida" if value == 1 else "doses perdidas"
    _append_visit_note(visit, f"{_pmo_event_time_label()} - {value} {label} nesta casa.")
    db.session.commit()
    write_note_to_sheet(visit)
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


# ——— Criação do "dia de vacinação" ————————————————————————————————————————

def _pmo_normalize_title(value: Any) -> str:
    """Normaliza um título de aba: sem acento, minúsculo, espaços colapsados."""
    text = _strip_accents(_normalize_text(value)).lower()
    return re.sub(r"\s+", " ", text).strip()


def _resolve_pmo_sheet_title(service, spreadsheet_id: str, wanted: str) -> str:
    """Acha o título real de uma aba de forma tolerante.

    Ordem de tentativa: igualdade normalizada (sem acento/maiúscula/espaços
    repetidos) → todas as palavras procuradas presentes na aba → substring em
    qualquer direção. Se nada casar, lista as abas disponíveis no erro.
    """
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
        .execute()
    )
    titles = [
        sheet.get("properties", {}).get("title", "")
        for sheet in metadata.get("sheets", [])
        if sheet.get("properties", {}).get("title")
    ]
    target = _pmo_normalize_title(wanted)

    for title in titles:  # 1) igualdade normalizada
        if _pmo_normalize_title(title) == target:
            return title

    target_tokens = set(target.split())
    for title in titles:  # 2) todas as palavras procuradas presentes na aba
        if target_tokens and target_tokens.issubset(set(_pmo_normalize_title(title).split())):
            return title

    for title in titles:  # 3) substring em qualquer direção
        normalized = _pmo_normalize_title(title)
        if target and (target in normalized or normalized in target):
            return title

    disponiveis = ", ".join(f"'{title}'" for title in titles) or "(nenhuma)"
    raise ValueError(
        f"Não encontrei a aba '{wanted}' na planilha PMO. Abas disponíveis: {disponiveis}."
    )


def _pmo_color_is_white(color: dict[str, float] | None) -> bool:
    """True quando a célula não tem cor de fundo (branca/neutra)."""
    if not color:
        return True
    return all(
        color.get(channel, 1.0) >= PMO_SCHEDULE_WHITE_THRESHOLD
        for channel in ("red", "green", "blue")
    )


def _pmo_scheduled_rows_from_backgrounds(backgrounds: list[dict[str, float] | None]) -> set[int]:
    """Linhas (1-based) já pintadas = já agendadas, devem ser puladas."""
    return {
        index
        for index, color in enumerate(backgrounds, start=1)
        if not _pmo_color_is_white(color)
    }


def _pmo_scheduled_source_rows(
    service, spreadsheet_id: str, sheet_title: str, max_rows: int
) -> set[int]:
    if max_rows <= 0:
        return set()
    response = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            ranges=[f"{_quote_sheet_title(sheet_title)}!A1:A{max_rows}"],
            fields="sheets(data(rowData(values(effectiveFormat(backgroundColor)))))",
            includeGridData=True,
        )
        .execute()
    )
    backgrounds: list[dict[str, float] | None] = []
    sheets = response.get("sheets", [])
    if sheets:
        data = sheets[0].get("data", [])
        if data:
            for row_data in data[0].get("rowData", []):
                values = row_data.get("values", [])
                color = (
                    values[0].get("effectiveFormat", {}).get("backgroundColor")
                    if values
                    else None
                )
                backgrounds.append(color)
    return _pmo_scheduled_rows_from_backgrounds(backgrounds)


def _pmo_house_animals(house: dict[str, Any]) -> int:
    return int(house.get("dogs") or 0) + int(house.get("cats") or 0)


def _pmo_is_condo(house: dict[str, Any]) -> bool:
    """True quando o complemento (coluna D) marca um condomínio."""
    cells = house.get("cells") or []
    complement = cells[3] if len(cells) > 3 else ""
    return "condominio" in _strip_accents(_normalize_text(complement)).lower()


def _pmo_condo_key(house: dict[str, Any]) -> str:
    """Chave que agrupa unidades do mesmo condomínio (endereço da coluna B)."""
    cells = house.get("cells") or []
    return _pmo_normalize_title(cells[1]) if len(cells) > 1 else ""


def _pmo_condo_label(house: dict[str, Any]) -> str:
    """Nome amigável do condomínio (ex.: 'Torino') extraído do complemento."""
    cells = house.get("cells") or []
    complement = _normalize_text(cells[3] if len(cells) > 3 else "")
    match = re.search(r"condom[ií]nios?\s+([0-9A-Za-zÀ-ú.\-]+)", complement, re.IGNORECASE)
    if match:
        return match.group(1).strip(" .-")
    return complement


def distribute_pmo_houses(
    houses: list[dict[str, Any]],
    *,
    seed_morning: list[dict[str, Any]] | None = None,
    condo_name: str = "",
) -> dict[str, Any]:
    """Distribui casas (na ordem recebida) entre manhã e tarde respeitando as metas.

    ``seed_morning`` (ex.: as unidades de um condomínio) já entram na manhã antes de
    completar com as demais casas; elas podem ultrapassar o máximo do turno, pois o
    condomínio deve ficar todo junto num turno só.
    """
    manha: list[dict[str, Any]] = list(seed_morning or [])
    tarde: list[dict[str, Any]] = []
    manha_animals = sum(_pmo_house_animals(h) for h in manha)
    tarde_animals = 0
    for house in houses:
        animals = _pmo_house_animals(house)
        # Teto duro do dia: casas avulsas nunca fazem o total passar de PMO_DAY_MAX_ANIMALS.
        # (O condomínio, que entra via seed_morning, é a única exceção.)
        if manha_animals + tarde_animals + animals > PMO_DAY_MAX_ANIMALS:
            break
        # Manhã primeiro, até o alvo de animais da manhã (e o limite de linhas).
        if len(manha) < PMO_MORNING_MAX_HOUSES and manha_animals + animals <= PMO_MORNING_TARGET_ANIMALS:
            manha.append(house)
            manha_animals += animals
            continue
        # Senão, tarde — respeitando só o limite de linhas do turno.
        if len(tarde) < PMO_AFTERNOON_MAX_HOUSES:
            tarde.append(house)
            tarde_animals += animals
            continue
        break
    return {
        "Manha": manha,
        "Tarde": tarde,
        "manha_animals": manha_animals,
        "tarde_animals": tarde_animals,
        "condo": condo_name,
    }


def plan_pmo_day(houses: list[dict[str, Any]]) -> dict[str, Any]:
    """Monta o dia escolhendo (no máximo) um condomínio + casas avulsas.

    Pega o primeiro condomínio na ordem de proximidade, coloca todas as suas
    unidades juntas na manhã e completa o dia com casas fora de condomínio. Os
    demais condomínios ficam para outros dias. Sem condomínio, distribui normal.
    """
    chosen_key = next((_pmo_condo_key(h) for h in houses if _pmo_is_condo(h)), "")
    condo_units = (
        [h for h in houses if _pmo_is_condo(h) and _pmo_condo_key(h) == chosen_key]
        if chosen_key
        else []
    )
    avulsas = [h for h in houses if not _pmo_is_condo(h)]
    condo_label = _pmo_condo_label(condo_units[0]) if condo_units else ""
    return distribute_pmo_houses(
        avulsas, seed_morning=condo_units, condo_name=condo_label
    )


def _pmo_empty_shift_slots(values: list[list[Any]], shift: str) -> list[int]:
    """Linhas-modelo vazias do turno: coluna R == turno e A..K em branco."""
    target = _normalize_shift(shift)
    slots: list[int] = []
    for index, row in enumerate(values, start=1):
        turno = _normalize_shift(row[17]) if len(row) > 17 else ""
        if turno != target:
            continue
        has_data = any(
            _normalize_text(row[col]) if len(row) > col else ""
            for col in range(PMO_SCHEDULE_SOURCE_COLUMNS)
        )
        if has_data:
            continue
        slots.append(index)
    return slots


def _pmo_template_insert_index(service, spreadsheet_id: str, template_title: str) -> int:
    """Índice para inserir a aba nova logo à direita da modelo 'Padrão'."""
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
        .execute()
    )
    for sheet in metadata.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("title") == template_title:
            return int(props.get("index", 0)) + 1
    return 0


def _pmo_duplicate_template(
    service, spreadsheet_id: str, template_gid: int, new_title: str, insert_index: int
) -> int:
    response = (
        service.spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "duplicateSheet": {
                            "sourceSheetId": template_gid,
                            "insertSheetIndex": insert_index,
                            "newSheetName": new_title,
                        }
                    }
                ]
            },
        )
        .execute()
    )
    for reply in response.get("replies", []):
        props = reply.get("duplicateSheet", {}).get("properties", {})
        if "sheetId" in props:
            return int(props["sheetId"])
    raise RuntimeError("Falha ao duplicar a aba modelo da campanha PMO.")


def _pmo_paint_source_rows(
    service, spreadsheet_id: str, source_gid: int, assignments: list[tuple[int, str]]
) -> None:
    requests = []
    for rownum, shift in assignments:
        color = PMO_SCHEDULE_COLORS.get(_normalize_shift(shift))
        if not color:
            continue
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": source_gid,
                        "startRowIndex": rownum - 1,
                        "endRowIndex": rownum,
                        "startColumnIndex": 0,
                        "endColumnIndex": 18,
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": color}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
        )
    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()


def _pmo_insert_cloned_rows(
    service, spreadsheet_id: str, sheet_gid: int, after_row: int, template_row: int, count: int
) -> bool:
    """Insere ``count`` linhas logo após ``after_row``, clonando ``template_row``.

    Usado quando um condomínio tem mais unidades do que as vagas do turno: as novas
    linhas herdam o formato e copiam as fórmulas/marcadores (coluna R) da linha
    modelo, virando vagas válidas do mesmo turno. Best-effort: devolve False se falhar.
    """
    if count <= 0:
        return True
    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "insertDimension": {
                            "range": {
                                "sheetId": sheet_gid,
                                "dimension": "ROWS",
                                "startIndex": after_row,
                                "endIndex": after_row + count,
                            },
                            "inheritFromBefore": True,
                        }
                    },
                    {
                        "copyPaste": {
                            "source": {
                                "sheetId": sheet_gid,
                                "startRowIndex": template_row - 1,
                                "endRowIndex": template_row,
                                "startColumnIndex": 0,
                                "endColumnIndex": 18,
                            },
                            "destination": {
                                "sheetId": sheet_gid,
                                "startRowIndex": after_row,
                                "endRowIndex": after_row + count,
                                "startColumnIndex": 0,
                                "endColumnIndex": 18,
                            },
                            "pasteType": "PASTE_NORMAL",
                        }
                    },
                ]
            },
        ).execute()
        return True
    except Exception:
        from flask import current_app
        try:
            current_app.logger.warning(
                "Falha ao inserir linhas extras para condomínio PMO", exc_info=True
            )
        except Exception:
            pass
        return False


_PMO_WEEKDAYS_PT = [
    "Segunda-Feira", "Terça-Feira", "Quarta-Feira",
    "Quinta-Feira", "Sexta-Feira", "Sábado", "Domingo",
]

_PMO_WA_SHIFT_HOURS = {
    "Manha": "8h30 às 11h30",
    "Tarde": "14h30 às 17h00",
}


def _pmo_wa_message_text(
    tutor_name: str,
    total_animals: int,
    street: str,
    number: str,
    complement: str,
    neighborhood: str,
    date_label: str,
    weekday: str,
    shift: str,
) -> str:
    hours = _PMO_WA_SHIFT_HOURS.get(shift, "8h30 às 11h30")
    parts = [f"{street}, {number}"]
    if complement:
        parts.append(complement)
    parts.append(neighborhood)
    address = " - ".join(parts)
    return (
        "Olá!\n"
        "Aqui é do setor de Controle de Vetores. Estamos organizando a Vacinação"
        " Contra a Raiva Animal 2026 e identificamos um cadastro em seu nome.\n"
        "\n"
        "Gostaríamos de confirmar algumas informações para que possamos vacinar seu"
        " animal com segurança:\n"
        "\n"
        f"Data sugerida para a vacinação: {date_label} ({weekday})\n"
        f"Horário: entre {hours}\n"
        "\n"
        "Para isso, pedimos sua colaboração respondendo às seguintes perguntas:\n"
        "\n"
        "• O animal está se alimentando normalmente?\n"
        "• O animal está tomando alguma medicação atualmente?\n"
        "• O endereço abaixo está correto? (se sim, favor confirmar, se não, corrigir)\n"
        "\n"
        f"REQUISITANTE: {tutor_name}\n"
        f"Quantidade de animais: {total_animals}\n"
        f"Endereço: {address}\n"
        "\n"
        "ATENÇÃO: caso não haja retorno, seu cadastro poderá ser substituído por outro.\n"
        "\n"
        "Agradecemos pela colaboração!"
    )


def _pmo_write_whatsapp_links(
    service,
    spreadsheet_id: str,
    date_label: str,
    target_date: date,
    wa_assignments: list[tuple[list[Any], int, str]],
) -> int:
    """Escreve hyperlinks wa.me nas colunas S e T da aba de dia recém-criada.

    wa_assignments: lista de (cells_A_K, rownum_na_aba, shift_key)
    Retorna o número de células de hyperlink gravadas.
    """
    weekday = _PMO_WEEKDAYS_PT[target_date.weekday()]
    quoted = _quote_sheet_title(date_label)

    data_updates: list[dict[str, Any]] = []
    for cells, rownum, shift in wa_assignments:
        padded = (list(cells) + [""] * PMO_SCHEDULE_SOURCE_COLUMNS)[:PMO_SCHEDULE_SOURCE_COLUMNS]
        tutor = str(padded[0] or "").strip()
        street = str(padded[1] or "").strip()
        number = str(padded[2] or "").strip()
        complement = str(padded[3] or "").strip()
        neighborhood = str(padded[4] or "").strip()
        phone1_raw = str(padded[5] or "").strip()
        phone2_raw = str(padded[6] or "").strip()

        if not tutor:
            continue

        try:
            dogs = int(float(padded[7] or 0))
        except (ValueError, TypeError):
            dogs = 0
        try:
            cats = int(float(padded[8] or 0))
        except (ValueError, TypeError):
            cats = 0
        total = max(dogs + cats, 1)

        phone1 = _pmo_format_phone_wa(phone1_raw)
        phone2 = _pmo_format_phone_wa(phone2_raw)
        if not phone1 and not phone2:
            continue

        msg = _pmo_wa_message_text(
            tutor, total, street, number, complement, neighborhood,
            date_label, weekday, shift,
        )
        encoded = urllib.parse.quote(msg)

        if phone1:
            url = f"https://wa.me/{phone1}?text={encoded}"
            data_updates.append({
                "range": f"{quoted}!S{rownum}",
                "values": [[f'=HYPERLINK("{url}","WhatsApp 1")']],
            })
        if phone2:
            url = f"https://wa.me/{phone2}?text={encoded}"
            data_updates.append({
                "range": f"{quoted}!T{rownum}",
                "values": [[f'=HYPERLINK("{url}","WhatsApp 2")']],
            })

    if data_updates:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": data_updates},
        ).execute()

    return len(data_updates)


def criar_dia_vacinacao(date_value: str) -> dict[str, Any]:
    """Cria a aba de um novo dia de vacinação a partir do modelo "padrão".

    Duplica a aba modelo, grava a data em Q12, distribui as próximas casas ainda não
    agendadas da "inscrições a agendar" entre manhã/tarde e pinta as linhas de origem
    (verde = manhã, azul = tarde) para marcar o agendamento.
    """
    target_date = _parse_date_object(date_value)
    if not target_date:
        raise ValueError("Informe uma data válida para o dia de vacinação.")
    date_label = target_date.strftime("%d/%m/%Y")

    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    spreadsheet_id = _extract_google_sheet_id(sheet_url)
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO inválido.")

    service = _get_sheets_service_rw()

    template_title = _resolve_pmo_sheet_title(
        service,
        spreadsheet_id,
        os.getenv(PMO_TEMPLATE_SHEET_TITLE_ENV, PMO_TEMPLATE_SHEET_DEFAULT_TITLE),
    )
    source_title = _resolve_pmo_sheet_title(
        service,
        spreadsheet_id,
        os.getenv(
            PMO_SCHEDULE_SOURCE_SHEET_TITLE_ENV, PMO_SCHEDULE_SOURCE_SHEET_DEFAULT_TITLE
        ),
    )

    if _get_sheet_gid(service, spreadsheet_id, date_label):
        raise ValueError(f"Já existe uma aba chamada '{date_label}' na planilha.")

    template_gid = _get_sheet_gid(service, spreadsheet_id, template_title)
    source_gid = _get_sheet_gid(service, spreadsheet_id, source_title)
    if not template_gid or not source_gid:
        raise RuntimeError("Não consegui localizar as abas modelo/origem da campanha PMO.")

    source_values = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet_title(source_title)}!A:R",
        )
        .execute()
        .get("values", [])
    )
    scheduled = _pmo_scheduled_source_rows(
        service, spreadsheet_id, source_title, len(source_values)
    )

    houses: list[dict[str, Any]] = []
    for row in parse_vacina_pmo_rows(source_values):
        src = int(row.get("sourceRow") or 0)
        if src <= 0 or src in scheduled:
            continue
        raw = source_values[src - 1] if src - 1 < len(source_values) else []
        houses.append(
            {
                "sourceRow": src,
                "tutor": row.get("tutor") or "",
                "dogs": row.get("dogs") or 0,
                "cats": row.get("cats") or 0,
                "cells": [_cell(raw, col) for col in range(PMO_SCHEDULE_SOURCE_COLUMNS)],
            }
        )

    plan = plan_pmo_day(houses)
    manha, tarde = plan["Manha"], plan["Tarde"]
    if not manha and not tarde:
        raise ValueError("Nenhuma casa nova para agendar (todas já estão pintadas).")

    insert_index = _pmo_template_insert_index(service, spreadsheet_id, template_title)
    new_gid = _pmo_duplicate_template(
        service, spreadsheet_id, int(template_gid), date_label, insert_index
    )
    new_tab = _quote_sheet_title(date_label)

    # RAW: grava a data como texto literal "DD/MM/AAAA"; assim o Google não a
    # reinterpreta pelo locale da planilha (que trocava dia/mês).
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{new_tab}!{PMO_DATE_MASTER_CELL}",
        valueInputOption="RAW",
        body={"values": [[date_label]]},
    ).execute()

    new_values = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{new_tab}!A:R")
        .execute()
        .get("values", [])
    )
    manha_slots = _pmo_empty_shift_slots(new_values, "Manha")
    tarde_slots = _pmo_empty_shift_slots(new_values, "Tarde")

    # Condomínio maior que o turno: insere linhas extras (clonando a última vaga)
    # para caber tudo junto na manhã, e relê as vagas (os índices mudam).
    manha_extra = len(manha) - len(manha_slots)
    if manha_extra > 0 and manha_slots:
        inserted = _pmo_insert_cloned_rows(
            service,
            spreadsheet_id,
            int(new_gid),
            after_row=manha_slots[-1],
            template_row=manha_slots[-1],
            count=manha_extra,
        )
        if inserted:
            new_values = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=f"{new_tab}!A:R")
                .execute()
                .get("values", [])
            )
            manha_slots = _pmo_empty_shift_slots(new_values, "Manha")
            tarde_slots = _pmo_empty_shift_slots(new_values, "Tarde")

    data_updates = []
    for house, rownum in zip(manha, manha_slots):
        cells = (house["cells"] + [""] * PMO_SCHEDULE_SOURCE_COLUMNS)[:PMO_SCHEDULE_SOURCE_COLUMNS]
        data_updates.append({"range": f"{new_tab}!A{rownum}:K{rownum}", "values": [cells]})
    for house, rownum in zip(tarde, tarde_slots):
        cells = (house["cells"] + [""] * PMO_SCHEDULE_SOURCE_COLUMNS)[:PMO_SCHEDULE_SOURCE_COLUMNS]
        data_updates.append({"range": f"{new_tab}!A{rownum}:K{rownum}", "values": [cells]})
    if data_updates:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": data_updates},
        ).execute()

    placed_manha = min(len(manha), len(manha_slots))
    placed_tarde = min(len(tarde), len(tarde_slots))
    assignments = [(house["sourceRow"], "Manha") for house in manha[:placed_manha]]
    assignments += [(house["sourceRow"], "Tarde") for house in tarde[:placed_tarde]]
    _pmo_paint_source_rows(service, spreadsheet_id, int(source_gid), assignments)

    wa_assignments = []
    for house, rownum in zip(manha[:placed_manha], manha_slots[:placed_manha]):
        wa_assignments.append((house["cells"], rownum, "Manha"))
    for house, rownum in zip(tarde[:placed_tarde], tarde_slots[:placed_tarde]):
        wa_assignments.append((house["cells"], rownum, "Tarde"))
    _pmo_write_whatsapp_links(service, spreadsheet_id, date_label, target_date, wa_assignments)

    return {
        "date": date_label,
        "sheetTitle": date_label,
        "sheetGid": str(new_gid),
        "spreadsheetId": spreadsheet_id,
        "morning": {"houses": placed_manha, "animals": plan["manha_animals"]},
        "afternoon": {"houses": placed_tarde, "animals": plan["tarde_animals"]},
        "condo": plan.get("condo") or "",
        "condoUnits": len(
            [h for h in manha if _pmo_is_condo(h)]
        ),
        "leftover": (len(manha) - placed_manha) + (len(tarde) - placed_tarde),
    }


def _pmo_last_numeric(row: list[Any]) -> int:
    """Último número da linha — na 'Controle de doses' é sempre o TOTAL da métrica."""
    last = 0
    for cell in row:
        text = _normalize_text(cell).replace(".", "").replace(",", ".")
        if not text:
            continue
        try:
            last = int(float(text))
        except (ValueError, TypeError):
            continue
    return last


def get_controle_de_doses_summary() -> dict[str, Any]:
    """Espelha a aba 'Controle de doses' (vacinados, doses, perdas por mês).

    Só leitura. Usa o último número de cada linha (Cachorros/Gatos/Doses/Perdas)
    como total do mês, o que é robusto às irregularidades da planilha manual.
    """
    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    spreadsheet_id = _extract_google_sheet_id(sheet_url)
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO inválido.")
    service = _get_sheets_service()
    title = _resolve_pmo_sheet_title(
        service,
        spreadsheet_id,
        os.getenv(PMO_DOSES_SHEET_TITLE_ENV, PMO_DOSES_SHEET_DEFAULT_TITLE),
    )
    values = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{_quote_sheet_title(title)}!A1:Z200")
        .execute()
        .get("values", [])
    )

    per_month: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in values:
        label = _strip_accents(_normalize_text(row[0] if row else "")).lower().rstrip(":").strip()
        if label in _PMO_MONTHS:
            current = {"month": label.capitalize(), "doses": 0, "dogs": 0, "cats": 0, "perdas": 0}
            per_month.append(current)
            continue
        if current is None:
            continue
        if label.startswith("doses utilizadas"):
            current["doses"] = _pmo_last_numeric(row)
        elif label == "cachorros":
            current["dogs"] = _pmo_last_numeric(row)
        elif label == "gatos":
            current["cats"] = _pmo_last_numeric(row)
        elif label == "perdas":
            current["perdas"] = _pmo_last_numeric(row)

    active = [m for m in per_month if (m["doses"] or m["dogs"] or m["cats"])]
    for m in active:
        m["vaccinated"] = m["dogs"] + m["cats"]
    totals = {
        "doses": sum(m["doses"] for m in active),
        "dogs": sum(m["dogs"] for m in active),
        "cats": sum(m["cats"] for m in active),
        "perdas": sum(m["perdas"] for m in active),
    }
    totals["vaccinated"] = totals["dogs"] + totals["cats"]
    totals["waste_pct"] = (
        round(100 * totals["perdas"] / totals["doses"], 1) if totals["doses"] else 0.0
    )
    return {"months": active, "totals": totals, "sheet_title": title}


# ——— Compilação automática do "Controle de doses" ————————————————————————————
# Espelha o gesto manual: somar cães/gatos/perdas de cada aba-dia e lançar uma
# coluna por data+turno no bloco do mês; a aba-dia compilada é pintada de verde.

PMO_DOSES_COMPILED_TAB_COLOR = {"red": 0.0, "green": 1.0, "blue": 0.0}
# Layout padrão dos blocos mensais: 8 vagas de dia (B..I) e total em J. Quando
# as vagas acabam, o compilador insere coluna antes do total em vez de estourar.
PMO_DOSES_DEFAULT_TOTAL_COL = 9
_PMO_DOSES_LABEL_DATE_RE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?")
PMO_DOSES_SHIFT_LABELS = {"Manha": "Manhã", "Tarde": "Tarde"}


def _pmo_col_letter(index: int) -> str:
    """Índice 0-based de coluna → letra A1 (suporta além de Z)."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _pmo_tab_color_is_green(color: dict[str, Any] | None) -> bool:
    if not color:
        return False
    red = float(color.get("red", 0.0))
    green = float(color.get("green", 0.0))
    blue = float(color.get("blue", 0.0))
    return green >= 0.9 and red <= 0.3 and blue <= 0.3


def _pmo_doses_label(value: Any) -> str:
    return _strip_accents(_normalize_text(value)).lower().rstrip(":").strip()


def _pmo_parse_doses_header_label(value: Any, default_year: int) -> tuple[date, str] | None:
    """Lê um rótulo de cabeçalho ("10/06/2026 - Manhã") → (data, turno|'')."""
    raw = _strip_accents(_normalize_text(value)).lower()
    if not raw:
        return None
    match = _PMO_DOSES_LABEL_DATE_RE.search(raw)
    if not match:
        return None
    year_text = match.group(3)
    year = int(year_text) if year_text else default_year
    if year < 100:
        year += 2000
    try:
        parsed = date(year, int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None
    shift = ""
    if "manh" in raw:
        shift = "Manha"
    elif "tard" in raw:
        shift = "Tarde"
    return parsed, shift


def _pmo_cell(values: list[list[Any]], row: int, col: int) -> Any:
    if row >= len(values):
        return ""
    cells = values[row]
    return cells[col] if col < len(cells) else ""


def _pmo_set_cell(values: list[list[Any]], row: int, col: int, value: Any) -> None:
    while len(values) <= row:
        values.append([])
    cells = values[row]
    while len(cells) <= col:
        cells.append("")
    cells[col] = value


def _pmo_cell_number(value: Any) -> float | None:
    text = _normalize_text(value).replace(".", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _pmo_day_sheet_counts(values: list[list[Any]]) -> dict[str, dict[str, int]]:
    """Soma M (cães) e N (gatos) das linhas de casa da aba-dia, por turno (R)."""
    counts = {shift: {"dogs": 0, "cats": 0} for shift in ("Manha", "Tarde")}
    for row in values[1:]:
        tutor = _normalize_text(row[0] if row else "")
        if not tutor:
            continue
        if _strip_accents(tutor).lower().startswith("nome completo"):
            continue  # cabeçalho repetido do bloco da tarde
        shift = _normalize_shift(row[17] if len(row) > 17 else "")
        if shift not in counts:
            continue
        counts[shift]["dogs"] += _parse_count(row[12] if len(row) > 12 else "")
        counts[shift]["cats"] += _parse_count(row[13] if len(row) > 13 else "")
    return counts


def _pmo_day_db_counts(spreadsheet_id: str, sheet_gid: str) -> tuple[dict[str, dict[str, int]], int]:
    """Vacinados e perdas por turno segundo o banco; também devolve o que ficou sem turno."""
    counts = {shift: {"dogs": 0, "cats": 0, "losses": 0} for shift in ("Manha", "Tarde")}
    no_shift = 0
    visits = PmoVaccinationVisit.query.filter_by(
        spreadsheet_id=spreadsheet_id, sheet_gid=str(sheet_gid)
    ).all()
    for visit in visits:
        shift = _normalize_shift(visit.shift)
        vaccinated_dogs = sum(
            1 for animal in visit.animals
            if (animal.status or "") == "vacinado" and animal.species != "gato"
        )
        vaccinated_cats = sum(
            1 for animal in visit.animals
            if (animal.status or "") == "vacinado" and animal.species == "gato"
        )
        losses = visit.losses or 0
        if shift not in counts:
            no_shift += vaccinated_dogs + vaccinated_cats + losses
            continue
        counts[shift]["dogs"] += vaccinated_dogs
        counts[shift]["cats"] += vaccinated_cats
        counts[shift]["losses"] += losses
    return counts, no_shift


def _pmo_find_doses_month_block(values: list[list[Any]], month_number: int) -> dict[str, int]:
    """Localiza o bloco do mês na 'Controle de doses' (índices 0-based)."""
    month_name = _PMO_MONTHS[month_number - 1]
    month_rows = [
        idx for idx, row in enumerate(values)
        if _pmo_doses_label(row[0] if row else "") in _PMO_MONTHS
    ]
    start = next(
        (idx for idx in month_rows if _pmo_doses_label(values[idx][0]) == month_name),
        None,
    )
    if start is None:
        raise ValueError(f"não encontrei o bloco de {month_name.capitalize()} na Controle de doses")
    end = next((idx for idx in month_rows if idx > start), len(values))

    rows: dict[str, int | None] = {"doses": None, "dogs": None, "cats": None, "perdas": None, "recebida": None}
    for idx in range(start + 1, end):
        label = _pmo_doses_label(values[idx][0] if values[idx] else "")
        if rows["doses"] is None and label.startswith("doses utilizadas"):
            rows["doses"] = idx
        elif rows["dogs"] is None and label == "cachorros":
            rows["dogs"] = idx
        elif rows["cats"] is None and label == "gatos":
            rows["cats"] = idx
        elif rows["perdas"] is None and label == "perdas":
            rows["perdas"] = idx
        elif rows["recebida"] is None and label.startswith("recebida"):
            rows["recebida"] = idx
    missing = [name for name in ("doses", "dogs", "cats", "perdas") if rows[name] is None]
    if missing:
        raise ValueError(
            f"bloco de {month_name.capitalize()} incompleto na Controle de doses "
            f"(faltam linhas: {', '.join(missing)})"
        )

    # Cabeçalho de datas: entre "Recebida no mês" e "Doses utilizadas", a linha
    # que já tem rótulos de data; senão, a última linha vazia do intervalo.
    header_start = (rows["recebida"] if rows["recebida"] is not None else start) + 1
    header_row = None
    empty_candidate = None
    for idx in range(header_start, rows["doses"]):
        cells = values[idx] if idx < len(values) else []
        tail = [cell for cell in cells[1:] if _normalize_text(cell)]
        if any(_PMO_DOSES_LABEL_DATE_RE.search(_normalize_text(cell)) for cell in tail):
            header_row = idx
            break
        if not tail and not _normalize_text(cells[0] if cells else ""):
            empty_candidate = idx
    if header_row is None:
        header_row = empty_candidate
    if header_row is None:
        raise ValueError(
            f"não achei a linha de cabeçalho de datas no bloco de {month_name.capitalize()}"
        )

    doses_cells = values[rows["doses"]] if rows["doses"] < len(values) else []
    last_numeric = None
    for col in range(1, len(doses_cells)):
        if _pmo_cell_number(doses_cells[col]) is not None:
            last_numeric = col
    total_col = last_numeric if last_numeric is not None and last_numeric >= PMO_DOSES_DEFAULT_TOTAL_COL else PMO_DOSES_DEFAULT_TOTAL_COL

    return {
        "header_row": header_row,
        "doses_row": rows["doses"],
        "dogs_row": rows["dogs"],
        "cats_row": rows["cats"],
        "perdas_row": rows["perdas"],
        "total_col": total_col,
    }


def _pmo_label_digits_match_date(value: Any, day: date) -> bool:
    """Reconhece rótulos com a data digitada errado ("0502/2026") comparando só os dígitos."""
    digits = _digits(value)
    return bool(digits) and digits in {day.strftime("%d%m%Y"), day.strftime("%d%m%y")}


def _pmo_resolve_doses_target_column(
    values: list[list[Any]], block: dict[str, int], day: date, shift: str
) -> tuple[int, bool]:
    """Coluna onde lançar (date, turno) → (índice, precisa inserir antes do total)."""
    header = values[block["header_row"]] if block["header_row"] < len(values) else []
    total_col = block["total_col"]
    for col in range(1, max(total_col, len(header))):
        cell = header[col] if col < len(header) else ""
        parsed = _pmo_parse_doses_header_label(cell, day.year)
        if parsed:
            if parsed[0] != day:
                continue
            if parsed[1] == shift:
                return col, False  # coluna já existe: atualiza no lugar (idempotente)
            if not parsed[1]:
                raise ValueError(
                    f"dia já representado por coluna manual sem turno para {day.strftime('%d/%m/%Y')} "
                    "no Controle de doses; separe por turno manualmente se quiser padronizar"
                )
            continue
        if _pmo_label_digits_match_date(cell, day):
            # Rótulo manual com erro de digitação: vale como coluna sem turno
            # daquele dia, para não duplicar o lançamento.
            raise ValueError(
                f"dia já representado por coluna manual sem turno (rótulo '{_normalize_text(cell)}' "
                f"≈ {day.strftime('%d/%m/%Y')}) no Controle de doses; corrija o rótulo se quiser padronizar"
            )
    metric_rows = (block["doses_row"], block["dogs_row"], block["cats_row"], block["perdas_row"])
    for col in range(1, total_col):
        if _normalize_text(_pmo_cell(values, block["header_row"], col)):
            continue
        # Coluna sem rótulo mas com dado não-zero = lançamento manual órfão; não sobrescreve.
        occupied = any(
            (_pmo_cell_number(_pmo_cell(values, row, col)) or 0) != 0 for row in metric_rows
        )
        if occupied:
            continue
        return col, False
    return total_col, True


def compile_controle_de_doses(*, dry_run: bool = False, include_compiled: bool = False) -> dict[str, Any]:
    """Compila as abas-dia no "Controle de doses" e pinta-as de verde.

    Regras: uma coluna por data+turno (rótulo "dd/mm/aaaa - Manhã/Tarde"); números
    vêm do banco do app e são conferidos com as somas M/N da própria aba-dia —
    divergência pula o dia com aviso em vez de compilar dado suspeito. Os totais
    do mês viram fórmula =SUM(...). Com dry_run=True nada é escrito.

    Por padrão só processa abas não-verdes (dias ainda não compilados). Com
    include_compiled=True revisita também as verdes para garantir que TODO dia
    tenha representação na tabela: colunas idênticas não geram escrita, dias já
    representados por coluna manual "só com a data" são respeitados, e perdas
    digitadas à mão são preservadas quando o app não conhece perdas do dia.
    """
    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    spreadsheet_id = _extract_google_sheet_id(sheet_url)
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO inválido.")
    service = _get_sheets_service_rw()
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title,tabColor))")
        .execute()
    )

    wanted_doses_title = os.getenv(PMO_DOSES_SHEET_TITLE_ENV, PMO_DOSES_SHEET_DEFAULT_TITLE)
    doses_title = ""
    doses_gid = None
    today = now_in_brazil().date()
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for sheet in metadata.get("sheets", []):
        props = sheet.get("properties", {})
        title = props.get("title", "")
        if _pmo_normalize_title(title) == _pmo_normalize_title(wanted_doses_title):
            doses_title = title
            doses_gid = props.get("sheetId")
            continue
        day = _parse_date_object(title)
        if not day:
            continue
        is_green = _pmo_tab_color_is_green(props.get("tabColor"))
        if is_green and not include_compiled:
            continue  # verde = já compilada
        if day > today:
            continue  # dia ainda não aconteceu
        if day.year != today.year:
            skipped.append({"title": title, "reason": "ano diferente do atual (aba modelo/teste?)"})
            continue
        candidates.append(
            {"title": title, "gid": str(props.get("sheetId", "")), "date": day, "green": is_green}
        )
    if not doses_title:
        raise RuntimeError(f"Aba '{wanted_doses_title}' não encontrada na planilha PMO.")
    candidates.sort(key=lambda item: item["date"])

    doses_values = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{_quote_sheet_title(doses_title)}!A1:AZ400")
        .execute()
        .get("values", [])
    )

    compiled: list[dict[str, Any]] = []
    unchanged: list[str] = []
    warnings: list[str] = []

    def _values_batch(data: list[dict[str, Any]]) -> None:
        if dry_run or not data:
            return
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": data},
        ).execute()

    for candidate in candidates:
        title = candidate["title"]
        day: date = candidate["date"]
        day_values = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"{_quote_sheet_title(title)}!A1:R200")
            .execute()
            .get("values", [])
        )
        sheet_counts = _pmo_day_sheet_counts(day_values)
        db_counts, no_shift = _pmo_day_db_counts(spreadsheet_id, candidate["gid"])

        total_day = sum(
            db_counts[shift]["dogs"] + db_counts[shift]["cats"] + db_counts[shift]["losses"]
            for shift in ("Manha", "Tarde")
        )
        if total_day == 0:
            skipped.append({"title": title, "reason": "sem vacinados nem perdas registrados"})
            continue
        if no_shift:
            warnings.append(
                f"{title}: {no_shift} vacinado(s)/perda(s) em casas sem turno definido ficaram fora."
            )

        mismatches = [
            f"{PMO_DOSES_SHIFT_LABELS[shift]} (planilha {sheet_counts[shift]['dogs']}🐕/{sheet_counts[shift]['cats']}🐈 "
            f"× app {db_counts[shift]['dogs']}🐕/{db_counts[shift]['cats']}🐈)"
            for shift in ("Manha", "Tarde")
            if sheet_counts[shift]["dogs"] != db_counts[shift]["dogs"]
            or sheet_counts[shift]["cats"] != db_counts[shift]["cats"]
        ]
        if mismatches:
            skipped.append(
                {
                    "title": title,
                    "reason": "contagens divergentes entre planilha e app: " + "; ".join(mismatches)
                    + ". Sincronize a aba no painel e confira antes de compilar.",
                }
            )
            continue

        try:
            block = _pmo_find_doses_month_block(doses_values, day.month)
        except ValueError as exc:
            skipped.append({"title": title, "reason": str(exc)})
            continue

        # Pré-checagem: um lançamento manual antigo "só com a data" bloqueia o dia
        # inteiro ANTES de qualquer escrita (evita compilar meio dia).
        try:
            for shift in ("Manha", "Tarde"):
                _pmo_resolve_doses_target_column(doses_values, block, day, shift)
        except ValueError as exc:
            skipped.append({"title": title, "reason": str(exc)})
            continue

        written_columns = []
        unchanged_columns = 0
        for shift in ("Manha", "Tarde"):
            shift_counts = db_counts[shift]
            if shift_counts["dogs"] + shift_counts["cats"] + shift_counts["losses"] == 0:
                continue
            # Resolve na hora de escrever: o turno anterior já marcou o cabeçalho
            # no modelo local, então cada turno ganha uma coluna própria.
            col, needs_insert = _pmo_resolve_doses_target_column(doses_values, block, day, shift)

            # Perdas digitadas à mão na tabela valem quando o app não conhece
            # nenhuma perda do turno (dias antigos, antes do campo no app).
            losses = shift_counts["losses"]
            if not losses and not needs_insert:
                existing_perdas = _pmo_cell_number(_pmo_cell(doses_values, block["perdas_row"], col))
                if existing_perdas:
                    losses = int(existing_perdas)
            doses = shift_counts["dogs"] + shift_counts["cats"] + losses

            label = f"{day.strftime('%d/%m/%Y')} - {PMO_DOSES_SHIFT_LABELS[shift]}"
            cell_writes = [
                (block["header_row"], label),
                (block["doses_row"], doses),
                (block["dogs_row"], shift_counts["dogs"]),
                (block["cats_row"], shift_counts["cats"]),
                (block["perdas_row"], losses),
            ]

            # Coluna já idêntica ao banco: não gasta escrita nem repinta nada.
            if not needs_insert:
                same = _normalize_text(_pmo_cell(doses_values, block["header_row"], col)) == label and all(
                    (_pmo_cell_number(_pmo_cell(doses_values, row_idx, col)) or 0) == value
                    for row_idx, value in cell_writes[1:]
                )
                if same:
                    unchanged_columns += 1
                    continue

            if needs_insert:
                if not dry_run:
                    service.spreadsheets().batchUpdate(
                        spreadsheetId=spreadsheet_id,
                        body={
                            "requests": [
                                {
                                    "insertDimension": {
                                        "range": {
                                            "sheetId": doses_gid,
                                            "dimension": "COLUMNS",
                                            "startIndex": col,
                                            "endIndex": col + 1,
                                        },
                                        "inheritFromBefore": True,
                                    }
                                }
                            ]
                        },
                    ).execute()
                # Mantém o modelo local alinhado com a grade (vale também no dry-run).
                for cells in doses_values:
                    if len(cells) > col:
                        cells.insert(col, "")
                block["total_col"] += 1

            data = []
            for row_idx, value in cell_writes:
                _pmo_set_cell(doses_values, row_idx, col, value)
                data.append(
                    {
                        "range": f"{_quote_sheet_title(doses_title)}!{_pmo_col_letter(col)}{row_idx + 1}",
                        "values": [[value]],
                    }
                )
            _values_batch(data)
            written_columns.append(
                {
                    "label": label,
                    "doses": doses,
                    "dogs": shift_counts["dogs"],
                    "cats": shift_counts["cats"],
                    "perdas": losses,
                }
            )

        if not written_columns:
            if unchanged_columns:
                # Tudo já estava em dia; garante só a cor da aba.
                if not candidate["green"] and not dry_run:
                    service.spreadsheets().batchUpdate(
                        spreadsheetId=spreadsheet_id,
                        body={
                            "requests": [
                                {
                                    "updateSheetProperties": {
                                        "properties": {
                                            "sheetId": int(candidate["gid"]),
                                            "tabColor": PMO_DOSES_COMPILED_TAB_COLOR,
                                        },
                                        "fields": "tabColor",
                                    }
                                }
                            ]
                        },
                    ).execute()
                unchanged.append(title)
            else:
                skipped.append({"title": title, "reason": "sem vacinados nem perdas registrados"})
            continue

        # Totais do mês viram fórmula — nunca mais ficam defasados.
        total_col = block["total_col"]
        last_day_letter = _pmo_col_letter(total_col - 1)
        total_letter = _pmo_col_letter(total_col)
        totals_data = []
        for row_idx in (block["doses_row"], block["dogs_row"], block["cats_row"], block["perdas_row"]):
            formula = f"=SUM(B{row_idx + 1}:{last_day_letter}{row_idx + 1})"
            # No modelo local guarda o número calculado (como a API devolveria),
            # para a detecção de "último numérico = total" continuar valendo.
            computed = int(
                sum(_pmo_cell_number(_pmo_cell(doses_values, row_idx, c)) or 0 for c in range(1, total_col))
            )
            _pmo_set_cell(doses_values, row_idx, total_col, computed)
            totals_data.append(
                {
                    "range": f"{_quote_sheet_title(doses_title)}!{total_letter}{row_idx + 1}",
                    "values": [[formula]],
                }
            )
        _values_batch(totals_data)

        if not dry_run and not candidate["green"]:
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": int(candidate["gid"]),
                                    "tabColor": PMO_DOSES_COMPILED_TAB_COLOR,
                                },
                                "fields": "tabColor",
                            }
                        }
                    ]
                },
            ).execute()

        compiled.append({"title": title, "date": day.isoformat(), "columns": written_columns})

    return {
        "compiled": compiled,
        "unchanged": unchanged,
        "skipped": skipped,
        "warnings": warnings,
        "dryRun": dry_run,
    }


# ——— Controle de frascos ——————————————————————————————————————————————————————
# Cada frasco tem 25 doses e, depois de aberto, vale 3 dias (o dia da abertura
# conta). A sobra de um dia abastece os seguintes dentro da validade; num
# histórico bem registrado os descartes viram perdas do dia e todo mês fecha em
# frascos inteiros — é exatamente o padrão dos totais (75/100/75/175/50...).

PMO_FRASCO_DOSES = int(os.getenv("PMO_FRASCO_DOSES", "25"))
PMO_FRASCO_VALIDADE_DIAS = int(os.getenv("PMO_FRASCO_VALIDADE_DIAS", "3"))


def _pmo_br_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def get_pmo_frascos_ledger() -> dict[str, Any]:
    """Reconstrói a linha do tempo de frascos a partir da "Controle de doses".

    Só leitura. A sobra é derivada (nunca digitada): sobra = sobra válida
    anterior + frascos abertos × doses − doses usadas. Inconsistências do
    registro (coluna sem data, mês que não fecha em frascos inteiros, sobra
    vencida sem descarte) viram anomalias/alertas em vez de quebrar a conta.
    """
    vial = PMO_FRASCO_DOSES
    validity = PMO_FRASCO_VALIDADE_DIAS
    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    spreadsheet_id = _extract_google_sheet_id(sheet_url)
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO inválido.")
    service = _get_sheets_service()
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))")
        .execute()
    )
    today = now_in_brazil().date()

    wanted_doses_title = os.getenv(PMO_DOSES_SHEET_TITLE_ENV, PMO_DOSES_SHEET_DEFAULT_TITLE)
    doses_title = ""
    next_scheduled: date | None = None
    for sheet in metadata.get("sheets", []):
        title = sheet.get("properties", {}).get("title", "")
        if _pmo_normalize_title(title) == _pmo_normalize_title(wanted_doses_title):
            doses_title = title
            continue
        day = _parse_date_object(title)
        if day and day > today and day.year == today.year:
            if next_scheduled is None or day < next_scheduled:
                next_scheduled = day
    if not doses_title:
        raise RuntimeError(f"Aba '{wanted_doses_title}' não encontrada na planilha PMO.")

    values = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{_quote_sheet_title(doses_title)}!A1:AZ400")
        .execute()
        .get("values", [])
    )

    per_day: dict[date, int] = {}
    anomalies: list[str] = []
    months_summary: list[dict[str, Any]] = []
    for month_number in range(1, 13):
        try:
            block = _pmo_find_doses_month_block(values, month_number)
        except ValueError:
            continue
        month_name = _PMO_MONTHS[month_number - 1].capitalize()
        header = values[block["header_row"]] if block["header_row"] < len(values) else []
        doses_cells = values[block["doses_row"]] if block["doses_row"] < len(values) else []
        month_sum = 0
        for col in range(1, block["total_col"]):
            doses_value = _pmo_cell_number(doses_cells[col] if col < len(doses_cells) else "")
            if not doses_value:
                continue
            doses_value = int(doses_value)
            month_sum += doses_value
            label_cell = header[col] if col < len(header) else ""
            parsed = _pmo_parse_doses_header_label(label_cell, today.year)
            if not parsed:
                anomalies.append(
                    f"{month_name}: coluna {_pmo_col_letter(col)} tem {doses_value} dose(s) sem rótulo "
                    "de data — fica fora da linha do tempo dos frascos. Dê um rótulo dd/mm/aaaa a ela."
                )
                continue
            if parsed[0].month != month_number:
                anomalies.append(
                    f"{month_name}: rótulo '{_normalize_text(label_cell)}' aponta para outro mês "
                    f"({_pmo_br_date(parsed[0])}) — confira se a data está certa."
                )
            per_day[parsed[0]] = per_day.get(parsed[0], 0) + doses_value
        if month_sum:
            months_summary.append(
                {
                    "month": month_name,
                    "doses": month_sum,
                    "vials": month_sum // vial,
                    "closes": month_sum % vial == 0,
                    "rest": month_sum % vial,
                }
            )
            if month_sum % vial:
                anomalies.append(
                    f"{month_name}: {month_sum} doses não fecham em frascos inteiros de {vial} "
                    f"(sobram {month_sum % vial}) — provável perda/descarte sem registro no mês."
                )

    days: list[dict[str, Any]] = []
    alerts: list[str] = []
    pending_expiry: list[dict[str, Any]] = []
    leftover = 0
    leftover_opened: date | None = None
    vials_total = 0
    for event_date in sorted(per_day):
        if leftover and leftover_opened and (event_date - leftover_opened).days >= validity:
            pending_expiry.append(
                {
                    "doses": leftover,
                    "opened": _pmo_br_date(leftover_opened),
                    "expired": _pmo_br_date(leftover_opened + timedelta(days=validity - 1)),
                }
            )
            leftover, leftover_opened = 0, None
        need = per_day[event_date]
        from_leftover = min(leftover, need)
        leftover -= from_leftover
        remaining = need - from_leftover
        new_vials = math.ceil(remaining / vial) if remaining else 0
        if new_vials:
            vials_total += new_vials
            leftover = new_vials * vial - remaining
            leftover_opened = event_date
        if leftover == 0:
            leftover_opened = None
        valid_until = leftover_opened + timedelta(days=validity - 1) if leftover_opened else None
        days.append(
            {
                "date": event_date.isoformat(),
                "dateLabel": _pmo_br_date(event_date),
                "doses": need,
                "fromLeftover": from_leftover,
                "vialsOpened": new_vials,
                "leftover": leftover,
                "leftoverValidUntil": _pmo_br_date(valid_until) if valid_until else "",
            }
        )

    for pend in pending_expiry:
        alerts.append(
            f"Sobra de {pend['doses']} dose(s) do frasco aberto em {pend['opened']} venceu em "
            f"{pend['expired']} sem aparecer como perda — registre o descarte como perdas desse dia."
        )

    current: dict[str, Any] = {"leftover": leftover, "opened": "", "validUntil": "", "expired": False}
    if leftover and leftover_opened:
        valid_until = leftover_opened + timedelta(days=validity - 1)
        current.update(
            {"opened": _pmo_br_date(leftover_opened), "validUntil": _pmo_br_date(valid_until)}
        )
        if today > valid_until:
            current["expired"] = True
            alerts.append(
                f"Sobra atual de {leftover} dose(s) (frasco aberto em {_pmo_br_date(leftover_opened)}) "
                f"venceu em {_pmo_br_date(valid_until)} — lance {leftover} perda(s) ou confirme o uso."
            )
        elif next_scheduled and next_scheduled > valid_until:
            alerts.append(
                f"Sobra de {leftover} dose(s) vence em {_pmo_br_date(valid_until)}, mas o próximo dia "
                f"agendado é {_pmo_br_date(next_scheduled)} — antecipe um dia de vacinação ou planeje o descarte."
            )

    return {
        "vialDoses": vial,
        "validityDays": validity,
        "vialsTotal": vials_total,
        "days": days,
        "months": months_summary,
        "current": current,
        "alerts": alerts,
        "anomalies": anomalies,
        "nextScheduled": _pmo_br_date(next_scheduled) if next_scheduled else "",
        "sheet_title": doses_title,
    }


def get_vacina_pmo_kpis() -> dict[str, Any]:
    """Indicadores da campanha, calculados do banco (mesma fonte do status-sync).

    Tudo é leitura — não escreve em planilha nenhuma.
    """
    from collections import Counter, defaultdict
    from scripts.sync_pmo_master_status_notes import (
        MASTER_SHEET_TITLE,
        STATUS_LABELS,
        _build_visit_index,
        _matching_visits,
        _overall_status,
    )

    all_visits = PmoVaccinationVisit.query.all()
    by_phone, by_name, by_user = _build_visit_index(all_visits)

    master_visits = [v for v in all_visits if v.sheet_title == MASTER_SHEET_TITLE]
    status_counts: Counter = Counter()
    registered_dogs = 0
    registered_cats = 0
    for visit in master_visits:
        matches = _matching_visits(visit, by_phone=by_phone, by_name=by_name, by_user=by_user)
        status_counts[_overall_status(matches)] += 1
        registered_dogs += int(visit.dogs or 0)
        registered_cats += int(visit.cats or 0)
    registered_animals = registered_dogs + registered_cats
    total_people = len(master_visits)

    # Vacinados reais (por espécie) nas abas datadas (os dias de campo).
    dated_visits = [v for v in all_visits if _parse_date_object((v.sheet_title or "").strip())]
    vac_dogs = sum(
        1 for v in dated_visits for a in v.animals if a.species == "cao" and a.status == "vacinado"
    )
    vac_cats = sum(
        1 for v in dated_visits for a in v.animals if a.species == "gato" and a.status == "vacinado"
    )
    vaccinated_animals = vac_dogs + vac_cats

    # Animais por dia (abas datadas) — para acompanhar a meta de 22–24.
    per_day: dict[str, int] = defaultdict(int)
    for v in dated_visits:
        per_day[v.sheet_title] += int(v.dogs or 0) + int(v.cats or 0)
    day_totals = list(per_day.values())
    avg_per_day = round(sum(day_totals) / len(day_totals), 1) if day_totals else 0.0

    source_title = os.getenv(
        PMO_SCHEDULE_SOURCE_SHEET_TITLE_ENV, PMO_SCHEDULE_SOURCE_SHEET_DEFAULT_TITLE
    )
    source_norm = _pmo_normalize_title(source_title)
    backlog = sum(
        1 for v in all_visits if _pmo_normalize_title(v.sheet_title) == source_norm
    )

    visited_keys = {"vacinado", "parcial", "ausente", "recusou", "remarcar"}
    atendidos = sum(c for k, c in status_counts.items() if k in visited_keys)
    vacinado_people = status_counts.get("vacinado", 0)
    coverage = (
        round(100 * vaccinated_animals / registered_animals, 1) if registered_animals else 0.0
    )

    label_map = dict(STATUS_LABELS)
    label_map.setdefault("sem_registro", "Sem registro")
    outcomes = [
        {
            "key": key,
            "label": label_map.get(key, key),
            "count": count,
            "pct": round(100 * count / total_people, 1) if total_people else 0.0,
        }
        for key, count in status_counts.most_common()
    ]

    return {
        "total_people": total_people,
        "atendidos": atendidos,
        "vacinado_people": vacinado_people,
        "registered_animals": registered_animals,
        "registered_dogs": registered_dogs,
        "registered_cats": registered_cats,
        "vaccinated_animals": vaccinated_animals,
        "vac_dogs": vac_dogs,
        "vac_cats": vac_cats,
        "coverage": coverage,
        "avg_per_day": avg_per_day,
        "days_count": len(day_totals),
        "backlog": backlog,
        "outcomes": outcomes,
        "per_day": [{"tab": t, "animals": a} for t, a in sorted(per_day.items())],
    }


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
                    requested_date=submitted_at.date(),
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
                existing.requested_date = submitted_at.date()
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


# ──────────────────────────────────────────────────────────────────────────────
# Cobertura ativa — validade da vacina antirrábica (365 dias)
# ──────────────────────────────────────────────────────────────────────────────

_PMO_VACCINE_VALIDITY_DAYS = 365


def _pmo_format_phone_wa(raw: str | None) -> str | None:
    """Retorna número limpo para wa.me (55XXXXXXXXXXX) ou None."""
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) in (10, 11):
        digits = "55" + digits
    return digits if len(digits) >= 12 else None


def get_vacina_pmo_cobertura_summary() -> dict[str, Any]:
    """Retorna 3 contadores rápidos de cobertura ativa, sem carregar objetos."""
    from sqlalchemy import func, case
    from models import PmoVaccinationAnimal, PmoVaccinationVisit

    today = date.today()
    threshold_30 = today + timedelta(days=30)

    rows = (
        db.session.query(
            PmoVaccinationAnimal.id,
            PmoVaccinationVisit.vaccine_date,
        )
        .join(PmoVaccinationVisit, PmoVaccinationAnimal.visit_id == PmoVaccinationVisit.id)
        .filter(
            PmoVaccinationAnimal.status == "vacinado",
            PmoVaccinationVisit.vaccine_date.isnot(None),
        )
        .with_entities(PmoVaccinationVisit.vaccine_date)
        .all()
    )

    protected = expiring = expired = 0
    for (vdate,) in rows:
        expiry = vdate + timedelta(days=_PMO_VACCINE_VALIDITY_DAYS)
        days_left = (expiry - today).days
        if days_left > 30:
            protected += 1
        elif days_left >= 0:
            expiring += 1
        else:
            expired += 1

    return {
        "protected": protected,
        "expiring": expiring,
        "expired": expired,
        "total": protected + expiring + expired,
    }


def get_vacina_pmo_cobertura_detail() -> list[dict[str, Any]]:
    """Lista detalhada de animais vacinados com dias restantes de proteção."""
    from models import PmoVaccinationAnimal, PmoVaccinationVisit

    today = date.today()

    animals = (
        db.session.query(PmoVaccinationAnimal)
        .join(PmoVaccinationVisit, PmoVaccinationAnimal.visit_id == PmoVaccinationVisit.id)
        .filter(
            PmoVaccinationAnimal.status == "vacinado",
            PmoVaccinationVisit.vaccine_date.isnot(None),
        )
        .order_by(PmoVaccinationVisit.vaccine_date.asc())
        .limit(500)
        .all()
    )

    result = []
    for a in animals:
        vdate = a.visit.vaccine_date
        expiry = vdate + timedelta(days=_PMO_VACCINE_VALIDITY_DAYS)
        days_left = (expiry - today).days

        if days_left > 30:
            status_key = "protected"
        elif days_left >= 0:
            status_key = "expiring"
        else:
            status_key = "expired"

        phone_raw = a.visit.phone1 or a.visit.phone2
        phone_wa = _pmo_format_phone_wa(phone_raw)

        msg = (
            f"Olá, {a.visit.tutor_name}! "
            f"A vacina antirrábica de *{a.name}* foi aplicada em "
            f"{vdate.strftime('%d/%m/%Y')} pela Prefeitura de Orlândia. "
            f"A proteção é válida por 1 ano e vence em *{expiry.strftime('%d/%m/%Y')}*. "
            f"Lembre-se de revacinar para manter seu pet protegido. 🐾"
        )

        result.append({
            "animal_name": a.name,
            "species": a.species,
            "tutor": a.visit.tutor_name,
            "phone": phone_raw or "",
            "phone_wa": phone_wa,
            "vaccine_date": vdate.strftime("%d/%m/%Y"),
            "expiry_date": expiry.strftime("%d/%m/%Y"),
            "days_left": days_left,
            "status_key": status_key,
            "wa_msg": msg,
        })

    result.sort(key=lambda x: x["days_left"])
    return result
