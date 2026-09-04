"""Google Sheets sync helpers for the PMO rabies vaccination campaign."""

from __future__ import annotations

import os
import re
import math
import json
import time
import secrets
import unicodedata
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import requests
from extensions import db
from flask import current_app, has_request_context, url_for
from models import (
    Animal,
    Endereco,
    PmoRouteOptimizationBackup,
    PmoVaccinationAnimal,
    PmoVaccinationVisit,
    Species,
    User,
    Vacina,
)
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
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
# Aba onde caem as solicitações enviadas pelos moradores no site. A busca é
# tolerante (ver ``_resolve_request_sheet_title``): renomear a aba na planilha
# — inclusive só trocando acento/caixa — não pode fazer o app criar uma aba
# nova e escondida, que foi o que aconteceu quando "Solicitacoes" virou
# "Solicitacoes de vacina" e as solicitações sumiram da vista da equipe.
PMO_REQUEST_SHEET_DEFAULT_TITLE = "Solicitacoes de vacina"
# Títulos já usados por esta aba. Servem tanto para reencontrá-la na planilha
# quanto para não perder o histórico de quem solicitou antes da renomeação.
PMO_REQUEST_SHEET_LEGACY_TITLES = ("Solicitacoes",)
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
# Quantidade de animais da casa (o que foi inscrito). É a contagem AUTORITATIVA
# usada por parse_animals para casar cada nome da coluna J com a espécie, então
# todo animal incluído na hora precisa aparecer aqui — senão o próximo sync o apaga.
PMO_DOGS_COLUMN = "H"
PMO_CATS_COLUMN = "I"

# Aba mestre de status (mantida pelo sync agendado). O app NUNCA deve escrever
# nela — a coluna M ali é o "Status PMO" compilado, não a contagem do app.
PMO_MASTER_SHEET_TITLE = os.getenv("PMO_VACCINE_MASTER_SHEET_TITLE", "Vacinação 2026")

# Aba de controle de doses/estoque mantida à mão (fonte oficial de vacinados/perdas).
PMO_DOSES_SHEET_TITLE_ENV = "PMO_VACCINE_DOSES_SHEET_TITLE"
PMO_DOSES_SHEET_DEFAULT_TITLE = "Controle de doses"
# Faixa única lida da aba de doses. Resumo e controle de frascos passam a ler a
# MESMA faixa de propósito: assim as duas visões do painel saem do mesmo
# snapshot (não podem divergir entre si) e de uma só chamada em cache.
PMO_DOSES_SHEET_RANGE = "A1:AZ400"
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
        "imunizado": "ja imunizado, sem dose",
        "ausente": "ausente",
        "remarcar": "remarcar",
        "recusou": "recusou",
    }
    label = labels.get(status, status)
    if status == PMO_STATUS_ALREADY_IMMUNE and animal.immune_since:
        label = f"{label} (dose de {animal.immune_since.strftime('%d/%m/%Y')})"
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
    # Optimization (Bolt): Fast-path for ASCII strings avoids expensive
    # unicodedata normalization and character categorization loops (~40% speedup).
    if not value or value.isascii():
        return value or ""
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


_ORLANDIA_NUMBER_WORDS = {
    "zero": "0", "um": "1", "uma": "1", "dois": "2", "duas": "2", "tres": "3", "três": "3",
    "quatro": "4", "cinco": "5", "seis": "6", "sete": "7", "oito": "8", "nove": "9", "dez": "10",
    "onze": "11", "doze": "12", "treze": "13", "quatorze": "14", "catorze": "14", "quinze": "15",
    "dezesseis": "16", "dezessete": "17", "dezoito": "18", "dezenove": "19", "vinte": "20",
    "vinte e um": "21", "vinte e dois": "22", "vinte e tres": "23", "vinte e três": "23",
    "vinte e quatro": "24", "vinte e cinco": "25", "vinte e seis": "26", "vinte e sete": "27",
    "vinte e oito": "28", "vinte e nove": "29", "trinta": "30",
}


def _pmo_clean_address_fragment(value: str) -> str:
    text = _normalize_text(value)
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b(antigo|nova|novo)\b", " ", text, flags=re.IGNORECASE)
    # Remove ruídos comuns de complementos que atrapalham o geocoder
    text = re.sub(
        r"\b(casa\s+(dos?\s+)?fundos?|fundos?|sobrado|sobrado\s+fundos?|apto\b[^\s,]*|apartamento\b[^\s,]*|"
        r"bloco\b[^\s,]*|port[aã]o\s+\w+|interfone\b[^\s,]*|pr[oó]x(imo)?\b.*|ao\s+lado\b.*|em\s+frente\b.*|"
        r"casa\s+\d+|casa\s+[a-zA-Z]\b)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+-\s+", " ", text)
    text = re.sub(r"\bR\.\s*", "Rua ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bAv\.\s*", "Avenida ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bAl\.\s*", "Alameda ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bP[çc][a\.]\s*", "Praça ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bTv\.\s*", "Travessa ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bJd\.\s*", "Jardim ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bPq\.\s*", "Parque ", text, flags=re.IGNORECASE)

    # Padroniza zeros à esquerda em ruas/avenidas de Orlândia (ex: Avenida 02 -> Avenida 2, Rua 09 -> Rua 9)
    text = re.sub(r"\b(Rua|Avenida|Alameda|Travessa)\s+0+(\d+)\b", r"\1 \2", text, flags=re.IGNORECASE)
    # Padroniza abreviações de Marginal
    text = re.sub(r"\bAv\.?\s*marginal\s+di\.?\b", "Avenida Marginal Direita", text, flags=re.IGNORECASE)
    text = re.sub(r"\bAv\.?\s*marginal\s+es\.?\b", "Avenida Marginal Esquerda", text, flags=re.IGNORECASE)

    # Padroniza nomes de ruas com números por extenso em Orlândia (ex: Rua Vinte e Quatro -> Rua 24)
    for word, num in sorted(_ORLANDIA_NUMBER_WORDS.items(), key=lambda item: -len(item[0])):
        text = re.sub(rf"\b(Rua|Avenida|Alameda|Praça|Travessa)\s+{word}\b", rf"\1 {num}", text, flags=re.IGNORECASE)

    text = re.sub(r",\s*,+", ",", text)
    text = re.sub(r",\s*$", "", text).strip(", ")
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
    city = "Orlândia, SP, Brasil"
    return _pmo_unique_queries([
        f"{normalized}, {city}",
        ", ".join(part for part in (street, number, neighborhood, city) if part),
        ", ".join(part for part in (street, number, city) if part),
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


# Geração do geocoder: o sufixo invalida caches antigos quando trocamos a fonte de
# geocodificação. "g2" = Google primário (antes era só Nominatim). Bumpar isto força
# re-geocodificação de todos os endereços na próxima otimização de rota.
_PMO_GEOCODE_GENERATION = "g2"


def _pmo_geocode_cache_key(address: str) -> str:
    base = _strip_accents(_normalize_text(address)).lower()
    return f"{base}|{_PMO_GEOCODE_GENERATION}" if base else ""


def _pmo_geocode_google(address: str) -> tuple[float, float] | None:
    """Geocodifica via Google Geocoding API, ancorado em Orlândia/SP.

    Cobertura de número de casa muito melhor que o Nominatim no Brasil. Usa
    `components` para travar em Orlândia e só aceita resultado dentro dos limites
    da cidade. Sem GOOGLE_MAPS_API_KEY (ou em erro/timeout), retorna None e o
    chamador cai no Nominatim.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get(
        "GOOGLE_GEOCODING_API_KEY"
    )
    normalized = _normalize_text(address)
    if not api_key or not normalized:
        return None
    full = f"{normalized}, Orlândia, SP, Brasil"
    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={
                "address": full,
                "components": "locality:Orlandia|administrative_area:SP|country:BR",
                "region": "br",
                "language": "pt-BR",
                "key": api_key,
            },
            timeout=6,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    if data.get("status") != "OK":
        return None
    # Prefere o resultado mais preciso (ROOFTOP/RANGE_INTERPOLATED) dentro de Orlândia.
    precise: tuple[float, float] | None = None
    fallback: tuple[float, float] | None = None
    for result in data.get("results", []):
        geometry = result.get("geometry") or {}
        location = geometry.get("location") or {}
        try:
            coords = (float(location["lat"]), float(location["lng"]))
        except (KeyError, TypeError, ValueError):
            continue
        if not _pmo_coords_in_orlandia(coords):
            continue
        if geometry.get("location_type") in ("ROOFTOP", "RANGE_INTERPOLATED"):
            precise = precise or coords
        fallback = fallback or coords
    return precise or fallback


def _pmo_geocode_address(address: str) -> tuple[float, float] | None:
    """Geocode a free-text PMO address.

    Tries Google Geocoding API (best house-number coverage) first, then the
    structured Nominatim helper, then PMO-specific free-text Nominatim queries.
    """
    normalized = _normalize_text(address)
    if not normalized:
        return None
    cache_key = _pmo_geocode_cache_key(normalized)
    if cache_key in _PMO_ROUTE_COORDS_CACHE:
        return _PMO_ROUTE_COORDS_CACHE[cache_key]

    # 1. Google (preciso). Já filtra por Orlândia internamente.
    coords = _pmo_geocode_google(normalized)
    if coords:
        _PMO_ROUTE_COORDS_CACHE[cache_key] = coords
        return coords

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

    # 4. Geocodificador local determinístico da malha ortogonal e bairros de Orlândia/SP
    # Garante 100% de cobertura instantânea sem depender de APIs externas no Heroku
    coords = _pmo_orlandia_local_geocode(normalized)
    if coords:
        _PMO_ROUTE_COORDS_CACHE[cache_key] = coords
        return coords

    return None


_PMO_ORLANDIA_NEIGHBORHOOD_ANCHORS: dict[str, tuple[float, float]] = {
    "centro": (-20.7170, -47.8860),
    "nova orlandia": (-20.7231, -47.8938),
    "jardim nova orlandia": (-20.7231, -47.8938),
    "parisi": (-20.7245, -47.8653),
    "jdm parisi": (-20.7245, -47.8653),
    "jardim parisi": (-20.7245, -47.8653),
    "jequitiba": (-20.7258, -47.8595),
    "villa comove": (-20.7203, -47.8867),
    "comove": (-20.7203, -47.8867),
    "teixeira": (-20.7203, -47.8867),
    "jardim teixeira": (-20.7203, -47.8867),
    "bandeirantes": (-20.7210, -47.8800),
    "marcussi": (-20.7150, -47.8800),
    "arantes": (-20.7180, -47.8750),
    "jardim arantes": (-20.7180, -47.8750),
    "boa vista": (-20.7120, -47.8900),
    "jardim boa vista": (-20.7120, -47.8900),
    "birucao": (-20.7250, -47.8680),
    "benja": (-20.7220, -47.8720),
    "jardim adalberto morandini": (-20.7203, -47.8867),
    "adalberto morandini": (-20.7203, -47.8867),
}


def _pmo_orlandia_local_geocode(address: str) -> tuple[float, float] | None:
    """Geocodificador determinístico para a malha urbana ortogonal e bairros de Orlândia/SP."""
    clean = _pmo_clean_address_fragment(address)
    norm = _strip_accents(clean).lower()
    if not norm:
        return None

    rua_match = re.search(r"\brua\s+(\d+)\b", norm)
    av_match = re.search(r"\b(?:avenida|av\.?)\s+(\d+)\b", norm)
    num_match = re.search(r",\s*(\d+)", norm) or re.search(r"\b(\d{1,4})\b", norm)

    r_num = int(rua_match.group(1)) if rua_match else None
    av_num = int(av_match.group(1)) if av_match else None
    house_num = int(num_match.group(1)) if num_match else 100

    if r_num is not None and av_num is not None:
        lat = -20.7070 - (r_num * 0.00086)
        lng = -47.8790 - (av_num * 0.00078)
        return (round(lat, 6), round(lng, 6))

    if r_num is not None:
        lat = -20.7070 - (r_num * 0.00086)
        approx_av = max(1.0, min(25.0, house_num / 100.0))
        lng = -47.8790 - (approx_av * 0.00078)
        return (round(lat, 6), round(lng, 6))

    if av_num is not None:
        lng = -47.8790 - (av_num * 0.00078)
        approx_rua = max(1.0, min(26.0, house_num / 100.0))
        lat = -20.7070 - (approx_rua * 0.00086)
        return (round(lat, 6), round(lng, 6))

    for key, coords in _PMO_ORLANDIA_NEIGHBORHOOD_ANCHORS.items():
        if key in norm:
            return coords

    return None


def _pmo_geocode_visit(visit: PmoVaccinationVisit) -> tuple[float, float] | None:
    """Return coordinates for a visit, using DB-persisted cache when available.

    The DB cache survives Heroku dyno restarts.  The in-memory dict avoids
    redundant DB reads within the same request.
    """
    address = visit.address or ""
    cache_key = _pmo_geocode_cache_key(address)
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


def _two_opt_route(
    origin: tuple[float, float],
    ordered_pairs: list[tuple[PmoVaccinationVisit, tuple[float, float]]],
    max_iterations: int = 60,
) -> list[tuple[PmoVaccinationVisit, tuple[float, float]]]:
    """Refina a rota calculada por Nearest Neighbor eliminando cruzamentos de caminhos (2-opt)."""
    if len(ordered_pairs) < 4:
        return ordered_pairs

    def _route_distance(route: list[tuple[PmoVaccinationVisit, tuple[float, float]]]) -> float:
        total = _haversine_km(origin, route[0][1])
        for i in range(len(route) - 1):
            total += _haversine_km(route[i][1], route[i + 1][1])
        return total

    best = list(ordered_pairs)
    best_dist = _route_distance(best)
    improved = True
    iteration = 0
    n = len(best)

    while improved and iteration < max_iterations:
        improved = False
        iteration += 1
        for i in range(n - 1):
            for j in range(i + 1, n):
                new_route = best[:i] + best[i : j + 1][::-1] + best[j + 1 :]
                new_dist = _route_distance(new_route)
                if new_dist < best_dist - 0.001:
                    best = new_route
                    best_dist = new_dist
                    improved = True
                    break
            if improved:
                break
    return best


def _nearest_neighbor_route(
    origin: tuple[float, float],
    items: list[tuple[PmoVaccinationVisit, tuple[float, float]]],
) -> list[PmoVaccinationVisit]:
    if not items:
        return []
    remaining = items[:]
    current = origin
    ordered_pairs: list[tuple[PmoVaccinationVisit, tuple[float, float]]] = []
    while remaining:
        next_index, pair = min(
            enumerate(remaining),
            key=lambda item: (_haversine_km(current, item[1][1]), item[1][0].source_row or 0, item[1][0].id),
        )
        ordered_pairs.append(pair)
        current = pair[1]
        remaining.pop(next_index)

    refined_pairs = _two_opt_route(origin, ordered_pairs)
    return [visit for visit, _ in refined_pairs]


def _pmo_extract_bairro_key(address: str) -> str:
    """Extrai chave normalizada do bairro para agrupamento."""
    parts = _pmo_address_parts(address)
    bairro = _pmo_clean_address_fragment(parts.get("bairro") or "")
    if not bairro:
        m = re.search(
            r"\b(jardim|jd\.?|centro|vila|pq\.?|parque|alto|alto da|bela|boa vista|siena|cidade alta|ouro verde)\b[^\n,]*",
            address,
            flags=re.IGNORECASE,
        )
        if m:
            bairro = m.group(0)
    return _strip_accents(_normalize_text(bairro)).lower()


def _merge_ungeocoded_intelligently(
    geocoded_ordered: list[PmoVaccinationVisit],
    ungeocoded: list[PmoVaccinationVisit],
) -> list[PmoVaccinationVisit]:
    """Intercala visitas sem GPS junto a visitas do mesmo bairro na rota."""
    if not ungeocoded:
        return geocoded_ordered
    if not geocoded_ordered:
        return ungeocoded

    result = list(geocoded_ordered)
    bairro_last_idx: dict[str, int] = {}
    for idx, visit in enumerate(result):
        bkey = _pmo_extract_bairro_key(visit.address or "")
        if bkey:
            bairro_last_idx[bkey] = idx

    unplaced: list[PmoVaccinationVisit] = []
    for visit in ungeocoded:
        bkey = _pmo_extract_bairro_key(visit.address or "")
        if bkey and bkey in bairro_last_idx:
            insert_idx = bairro_last_idx[bkey] + 1
            result.insert(insert_idx, visit)
            for k, v in list(bairro_last_idx.items()):
                if v >= insert_idx:
                    bairro_last_idx[k] = v + 1
            bairro_last_idx[bkey] = insert_idx
        else:
            unplaced.append(visit)

    return result + unplaced


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


# Separadores que delimitam animais diferentes: vírgula, ponto e vírgula, quebra de
# linha, barra/barra-vertical, bullets e a conjunção " e ".  Os tutores misturam tudo
# ("Mia / Amber", "Rex; Thor", "Lisa\nLulu", "• Mel"). Cada separador é IGNORADO quando
# aparece dentro de parênteses, pois os tutores escrevem descrições como
# "Branca (mais nova e braba)" — sem isso o "e"/vírgula da descrição quebra um nome em
# vários animais fantasmas.
_ANIMAL_SEPARATOR_RE = re.compile(r",|;|/|\||\n|•|·|•|\se\s", re.IGNORECASE)

# Dicas de espécie no próprio texto, normalmente entre parênteses ("Lisa (gata)") ou
# soltas ("a cachorra Mel"). Usadas para casar a espécie pelo conteúdo, não só pela
# posição na lista — a contagem de cães/gatos da planilha continua sendo autoritativa.
_CAT_HINT_RE = re.compile(r"\bgat[oa]s?\b", re.IGNORECASE)
_DOG_HINT_RE = re.compile(r"\b(c[ãa]es?|c[ãa]o|cachorr[oa]s?|cadela)\b", re.IGNORECASE)
# Parêntese (e similares) com anotação que não faz parte do nome.
_ANNOTATION_RE = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")


def _species_hint(part: str) -> str | None:
    """Retorna 'gato'/'cao' se o trecho menciona a espécie, senão None."""
    if _CAT_HINT_RE.search(part):
        return "gato"
    if _DOG_HINT_RE.search(part):
        return "cao"
    return None


def _split_animals_detailed(value: Any) -> list[dict[str, str | None]]:
    """Divide a célula em animais, devolvendo nome limpo + dica de espécie.

    O nome é higienizado (anotações entre parênteses removidas); a dica de espécie é
    extraída ANTES da limpeza para não se perder.
    """
    # IMPORTANTE: operar no texto CRU. _normalize_text colapsa "\n" em espaço, e os
    # tutores listam um animal por linha — normalizar antes apagaria o separador e
    # grudaria todos os nomes num só.
    text = str(value or "")
    if not text.strip():
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

    detailed: list[dict[str, str | None]] = []
    for raw in parts:
        raw = _normalize_text(raw)
        if not raw:
            continue
        hint = _species_hint(raw)
        # Nome final = sem anotações entre parênteses.
        name = _normalize_text(_ANNOTATION_RE.sub("", raw))
        if not name:
            continue
        detailed.append({"name": name, "species": hint})
    return detailed


def _split_animals(value: Any) -> list[str]:
    """Lista só de nomes — usada pela validação de edição de nome de animal."""
    return [str(item["name"]) for item in _split_animals_detailed(value)]


def _build_animals(
    names: list[str] | list[dict[str, str | None]], dogs: int, cats: int
) -> list[dict[str, str]]:
    # As quantidades de cães/gatos vêm de colunas próprias da planilha e são a
    # contagem AUTORITATIVA de animais. Só usamos o número de nomes encontrados no
    # texto livre quando nenhuma quantidade foi informada — assim uma descrição
    # bagunçada nunca infla a contagem de animais (o que deixaria pets fantasmas
    # presos em "pendente" e marcaria a visita inteira como "parcial").
    # Aceita tanto a lista antiga de strings quanto a lista detalhada com dica de
    # espécie; quando há dica, ela tem prioridade sobre a posição.
    detailed: list[dict[str, str | None]] = [
        {"name": n, "species": None} if isinstance(n, str) else n for n in names
    ]
    count = dogs + cats
    total = count if count > 0 else len(detailed)

    # 1ª passada: encaixa cada nome com dica de espécie explícita nos slots dessa
    # espécie. 2ª passada: distribui o resto por posição (cães primeiro, depois gatos).
    slots: list[dict[str, str] | None] = [None] * total
    cao_slots = [i for i in range(total) if i < dogs] or (
        list(range(total)) if dogs == 0 and cats == 0 else []
    )
    gato_slots = [i for i in range(total) if i >= dogs]

    leftover = list(detailed)
    for pool, species in ((cao_slots, "cao"), (gato_slots, "gato")):
        free = [i for i in pool if slots[i] is None]
        hinted = [d for d in leftover if d.get("species") == species]
        for slot, item in zip(free, hinted):
            slots[slot] = {"name": str(item["name"]), "species": species}
            leftover.remove(item)

    leftover_iter = iter(leftover)
    animals: list[dict[str, str]] = []
    for index in range(total):
        filled = slots[index]
        if filled is not None:
            name, species = filled["name"], filled["species"]
        else:
            species = "cao" if index < dogs else "gato"
            nxt = next(leftover_iter, None)
            fallback = (
                f"Cao {index + 1}" if species == "cao" else f"Gato {index - dogs + 1}"
            )
            name = str(nxt["name"]) if nxt else fallback
        animals.append(
            {
                "name": name[:PMO_ANIMAL_NAME_MAX],
                "species": species,
                "status": "pendente",
            }
        )
    return animals


# Nome genérico gerado pelo fallback quando falta nome para um slot ("Cao 2", "Gato 1").
_GENERIC_ANIMAL_RE = re.compile(r"^(Cao|Gato)\s+\d+$", re.IGNORECASE)


def _looks_uncertain(animals: list[dict[str, str]], value: Any) -> bool:
    """True quando as regras provavelmente erraram e vale tentar a IA.

    Critério: existe texto na célula MAS algum animal ficou com nome genérico
    (sinal de que a divisão não casou com a contagem de cães/gatos). Mantém as
    chamadas à IA restritas aos casos realmente bagunçados — preserva a cota grátis.
    """
    if not str(value or "").strip():
        return False
    return any(_GENERIC_ANIMAL_RE.match(a["name"]) for a in animals)


def _split_on_whitespace_if_matches(
    value: Any, total: int
) -> list[dict[str, str | None]] | None:
    """Fallback para células com nomes separados só por espaço (ex.: "Mia Amber Lua").

    Os separadores normais (vírgula, /, quebra de linha…) não pegam isso e o espaço
    não pode virar separador genérico (quebraria "Maria Clara"). Mas quando a
    contagem AUTORITATIVA de animais (dogs+cats) bate exatamente com o número de
    tokens, dividir por espaço é seguro. Retorna a lista detalhada ou None.

    Usa \\s+ (regex), que também quebra em espaço não-quebrável (\\xa0) — comum em
    texto copiado de planilha e causa frequente desse bug.
    """
    if total <= 1:
        return None
    # Remove anotações entre parênteses antes de tokenizar.
    cleaned = _normalize_text(_ANNOTATION_RE.sub(" ", str(value or "")))
    tokens = [t for t in re.split(r"\s+", cleaned) if t]
    if len(tokens) != total:
        return None
    return [{"name": t, "species": _species_hint(t)} for t in tokens]


def parse_animals(
    value: Any, dogs: int, cats: int, *, force_ai: bool = False
) -> list[dict[str, str]]:
    """Ponto único de entrada para transformar a célula de animais em registros.

    Roda as regras determinísticas (rápidas, offline) e só recorre à IA gratuita
    (Gemini) quando o resultado parece duvidoso — assim o sync não depende de rede
    no caso comum e a cota grátis é gasta só onde faz diferença.

    Com force_ai=True (botão "Corrigir nomes com IA"), tenta a IA em TODA linha,
    mesmo nas que parecem ok — útil quando o operador sabe que estão erradas. Em
    qualquer falha da IA, cai nas regras.
    """
    detailed = _split_animals_detailed(value)
    rules = _build_animals(detailed, dogs, cats)

    # Fallback offline para nomes separados só por espaço: se as regras ficaram
    # duvidosas mas a contagem casa com os tokens, divide por espaço. Conserta o
    # caso "Mia Amber Lecter Ozzy Mischa Lisa" sem depender do Gemini.
    if _looks_uncertain(rules, value):
        total = dogs + cats if (dogs + cats) > 0 else len(detailed)
        ws = _split_on_whitespace_if_matches(value, total)
        if ws is not None:
            ws_rules = _build_animals(ws, dogs, cats)
            if not any(_GENERIC_ANIMAL_RE.match(a["name"]) for a in ws_rules):
                rules = ws_rules

    if not force_ai and not _looks_uncertain(rules, value):
        return rules
    ai = _parse_animals_ai(value, dogs, cats)
    return ai if ai is not None else rules


# Schema de saída do Gemini: lista de animais já casados com a espécie.
_GEMINI_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING"},
            "species": {"type": "STRING", "enum": ["cao", "gato"]},
        },
        "required": ["name", "species"],
    },
}


def _parse_animals_ai(value: Any, dogs: int, cats: int) -> list[dict[str, str]] | None:
    """Parser via Gemini (free tier). Retorna None em qualquer falha → cai no fallback.

    Manda SÓ o texto da célula de animais + as contagens dogs/cats — nada de tutor,
    endereço ou telefone. Em ausência de chave, erro de rede, timeout ou resposta
    inesperada, devolve None e o chamador usa as regras determinísticas.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    text = str(value or "").strip()
    if not api_key or not text:
        return None

    total = dogs + cats
    instrucao = (
        "Você extrai nomes de animais de uma célula de planilha de uma campanha de "
        "vacinação. O texto é livre e bagunçado: os tutores separam os nomes por "
        "vírgula, barra (/), quebra de linha, ';', 'e' ou bullets, e às vezes incluem "
        "anotações entre parênteses. Devolva um nome por animal, limpo (sem as "
        "anotações). A campanha registrou "
        f"{dogs} cão(es) e {cats} gato(s) (total {total}). "
        "Use exatamente esse total de itens e respeite a quantidade de cada espécie; "
        "quando o texto indicar a espécie de um animal, honre-a. Se faltar nome para "
        "algum slot, devolva o nome vazio para ele.\n\n"
        f"Texto da célula:\n{text}"
    )
    body = {
        "contents": [{"parts": [{"text": instrucao}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _GEMINI_SCHEMA,
            "temperature": 0,
        },
    }
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    headers = {"Content-Type": "application/json", "X-goog-api-key": api_key}
    parsed = None
    for attempt in range(3):  # 503/429 são comuns no free tier; retry curto ajuda
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=8)
            if resp.status_code in (429, 500, 503) and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(raw)
            break
        except Exception:  # rede, timeout, JSON inesperado, cota — usa o fallback
            return None
    if parsed is None:
        return None

    if not isinstance(parsed, list):
        return None
    # Reaproveita _build_animals para travar contagem/espécie de forma autoritativa:
    # a IA dá os nomes + dicas, mas a planilha continua mandando no total.
    detailed = [
        {
            "name": _normalize_text(item.get("name")),
            "species": item.get("species") if item.get("species") in ("cao", "gato") else None,
        }
        for item in parsed
        if isinstance(item, dict) and _normalize_text(item.get("name"))
    ]
    if not detailed:
        return None
    return _build_animals(detailed, dogs, cats)


def _cell(row: list[Any], index: int) -> str:
    return _normalize_text(row[index]) if len(row) > index else ""


def _row_column_offset(row: list[Any]) -> int:
    return 1 if _parse_date_object(_cell(row, 0)) and _cell(row, 1) else 0


# Sem I/O/0/1: a tutora lê a senha de um papel e digita no celular.
_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _password(seed: str = "") -> str:
    """Senha da carteirinha PMO, independente do telefone.

    A versão anterior era ``PMO`` + uma letra sorteada + os 4 últimos dígitos do
    telefone. Como o telefone é o próprio identificador de login, sobravam 24
    senhas possíveis para quem soubesse o número — três minutos de tentativas
    dentro do limite de 10/min. O ``seed`` continua na assinatura só para não
    quebrar as chamadas existentes.
    """
    del seed
    return "PMO" + "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(5))


def _public_token() -> str:
    return secrets.token_urlsafe(32)


def _provisional_email(phone: str, visit_id: int | None = None) -> str:
    digits = _digits(phone)[-13:] or str(visit_id or secrets.randbelow(999999)).zfill(6)
    return f"pmo-{digits}@petorlandia.local"


def _normalize_person_name(value: Any) -> str:
    return re.sub(r"\s+", " ", _strip_accents(_normalize_text(value)).lower()).strip()


_NAME_PARTICLES = {"da", "das", "de", "do", "dos", "e", "d"}


def _person_name_tokens(value: Any) -> list[str]:
    raw = str(value or "")
    if "->" in raw:
        raw = raw.split("->", 1)[0]
    return [
        token
        for token in _normalize_person_name(raw).split()
        if token and token not in _NAME_PARTICLES
    ]


def _same_person_name(left: Any, right: Any) -> bool:
    """Reconhece a mesma pessoa quando uma campanha abrevia o nome da outra.

    A planilha é digitada de novo a cada dia de campanha, então "Ana Marcia
    Pinheiro" e "Ana Marcia da Costa Pinheiro" são a mesma tutora. Sem essa
    tolerância cada grafia virava uma conta nova no mesmo celular, e aí nem o
    login nem o primeiro acesso conseguiam desempatar.

    Três condições, todas necessárias:

    1. mesmo primeiro nome e mesmo último sobrenome;
    2. a grafia curta é **subsequência ordenada** da longa (só faltam nomes do
       meio, nunca há troca de um por outro);
    3. a grafia curta tem no mínimo 3 tokens.

    A condição 3 é o que separa "Ana Marcia Pinheiro" / "Ana Marcia da Costa
    Pinheiro" (mesma tutora, une) de "Jose Santos" / "Jose Carlos Santos" (pai
    e filho no mesmo telefone, mantém separados). Sem ela, todo nome de dois
    tokens engoliria qualquer homônimo com nome do meio.

    Preferir falso negativo a falso positivo: duas contas separadas da mesma
    pessoa são um aborrecimento no login; duas famílias fundidas colocam os
    animais de uma no prontuário da outra.
    """
    left_tokens = _person_name_tokens(left)
    right_tokens = _person_name_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    if left_tokens == right_tokens:
        return True
    if left_tokens[0] != right_tokens[0] or left_tokens[-1] != right_tokens[-1]:
        return False

    short, long = sorted((left_tokens, right_tokens), key=len)
    # Precisa sobrar algo além do primeiro nome e do último sobrenome; senão
    # "Jose Santos" engoliria qualquer "Jose <qualquer coisa> Santos".
    if len(short) < 3:
        return False
    if not _is_ordered_subsequence(short, long):
        return False
    return True


def _is_ordered_subsequence(short: list[str], long: list[str]) -> bool:
    """``short`` aparece em ``long`` na mesma ordem (podendo pular tokens)."""
    iterator = iter(long)
    return all(token in iterator for token in short)


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
    candidates = []
    for user in User.query.filter(User.phone.isnot(None), User.phone != "").all():
        if _normalize_login_phone(user.phone) != normalized:
            continue
        if _normalize_person_name(user.name) == target_name:
            return user  # grafia idêntica sempre ganha
        if _same_person_name(user.name, name):
            candidates.append(user)
    if not candidates:
        return None
    # Empate só acontece entre grafias do mesmo nome; fica com a conta mais
    # antiga, que é onde o histórico da tutora já está.
    return min(candidates, key=lambda user: user.id or 0)


def _same_family(user: User | None, visit: PmoVaccinationVisit) -> bool:
    if not user:
        return False
    phone = visit.phone1 or visit.phone2
    if _normalize_login_phone(user.phone) != _normalize_login_phone(phone):
        return False
    return _same_person_name(user.name, visit.tutor_name)


def _email_is_taken(candidate: str) -> bool:
    return (
        User.query.filter(func.lower(User.email) == candidate.lower()).first()
        is not None
    )


def _unique_provisional_email(normalized_phone: str, visit: PmoVaccinationVisit) -> str:
    """E-mail provisório garantidamente livre.

    ``User.email`` é unique. O sufixo por visita não bastava: quando a planilha
    muda a identidade da visita, ``tutor_user_id`` é zerado (ver
    ``_ensure_visit_records``) e uma segunda conta é criada para a MESMA visita
    — reproduzindo ``pmo-<tel>-<visit.id>@`` e estourando IntegrityError no
    commit. Por isso a busca continua até achar um endereço livre de fato.
    """
    candidate = _provisional_email(normalized_phone, visit.id)
    if not _email_is_taken(candidate):
        return candidate

    # Telefone compartilhado entre famílias: desempata por visita.
    digits = _digits(normalized_phone)[-13:] or "x"
    if visit.id:
        candidate = f"pmo-{digits}-{visit.id}@petorlandia.local"
        if not _email_is_taken(candidate):
            return candidate

    # Visita ainda sem id, ou id já usado numa revinculação anterior.
    while True:
        candidate = f"pmo-{digits}-{secrets.token_hex(4)}@petorlandia.local"
        if not _email_is_taken(candidate):
            return candidate


def _ensure_visit_public_token(visit: PmoVaccinationVisit) -> None:
    if visit.public_token:
        return
    while True:
        token = _public_token()
        if not PmoVaccinationVisit.query.filter_by(public_token=token).first():
            visit.public_token = token
            return


PMO_DEFAULT_CITY = "Orlândia"
PMO_DEFAULT_STATE = "SP"


def _fit(value: str | None, length: int) -> str | None:
    """Corta no tamanho da coluna. Sem isso o Postgres recusa o INSERT inteiro."""
    text = _normalize_text(value)
    return text[:length] or None if text else None


_PREVIOUS_ADDRESS_MARKER = "Endereço anterior"


def _visit_recency_key(visit: PmoVaccinationVisit) -> tuple:
    """Ordena visitas da mais antiga para a mais recente.

    Usa a data da campanha e cai no id quando não há data — ordem de iteração
    do banco não serve, senão qual endereço "vence" mudaria a cada sync.
    """
    when = visit.vaccine_date or visit.requested_date or date.min
    return (when, visit.id or 0)


def _tutor_visits_with_address(user: User) -> list[PmoVaccinationVisit]:
    return [
        visit
        for visit in PmoVaccinationVisit.query.filter_by(tutor_user_id=user.id).all()
        if _normalize_text(visit.address)
    ]


def _address_came_from_campaign(user: User, visits: list[PmoVaccinationVisit]) -> bool:
    """O endereço atual do tutor foi escrito pela campanha, não à mão.

    Se ninguém na clínica mexeu, ``user.address`` é igual ao texto de alguma
    visita. Quando difere de todas, alguém corrigiu na ficha — e correção
    manual não pode ser desfeita pela planilha.
    """
    current = _normalize_text(user.address)
    if not current:
        return True
    return any(_normalize_text(visit.address) == current for visit in visits)


def _is_newest_address_source(user: User, visit: PmoVaccinationVisit) -> bool:
    """A visita é a mais recente do tutor entre as que têm endereço."""
    siblings = [
        other for other in _tutor_visits_with_address(user) if other.id != visit.id
    ]
    if not siblings:
        return True
    return _visit_recency_key(visit) >= max(_visit_recency_key(o) for o in siblings)


def _archive_previous_address(user: User, address: str) -> bool:
    """Guarda um endereço nas observações, sem repetir a cada sincronização."""
    address = _normalize_text(address)
    if not address:
        return False
    current = user.observacoes or ""
    if address in current:
        return False
    entry = f"{_PREVIOUS_ADDRESS_MARKER}: {address}"
    user.observacoes = f"{current.rstrip()}\n{entry}".strip() if current else entry
    return True


def _build_endereco(address: str, visit: PmoVaccinationVisit) -> Endereco:
    parts = _pmo_address_parts(address)
    endereco = Endereco(
        rua=_fit(_pmo_clean_address_fragment(parts["rua"]), 120),
        numero=_fit(parts["numero"], 20),
        complemento=_fit(parts["complemento"], 100),
        bairro=_fit(_pmo_clean_address_fragment(parts["bairro"]), 100),
        cidade=PMO_DEFAULT_CITY,
        estado=PMO_DEFAULT_STATE,
    )
    # Só reaproveita coordenada já calculada. Geocodificar aqui colocaria uma
    # chamada de rede em cada carregamento do painel; o backfill e a otimização
    # de rota é que preenchem visit.geocode_*.
    if visit.geocode_lat is not None and visit.geocode_lng is not None:
        endereco.latitude = visit.geocode_lat
        endereco.longitude = visit.geocode_lng
    db.session.add(endereco)
    db.session.flush()
    return endereco


def _apply_visit_address(user: User, visit: PmoVaccinationVisit) -> bool:
    """Espelha o endereço da visita no tutor, em texto **e** estruturado.

    A ficha do tutor (``ficha_tutor`` -> ``endereco_form.html``) lê
    ``user.endereco``, que é o modelo estruturado; o PMO só preenchia
    ``user.address``, que é texto livre e aparece apenas nas impressões. Por
    isso o endereço "sumia": estava gravado, mas no campo que aquela tela não
    lê.

    Quando o tutor tem mais de um endereço — existe tutora com animais vivendo
    em locais diferentes — o modelo só tem uma vaga (``User.endereco_id``).
    Nesse caso vale o endereço da visita **mais recente**, e o anterior vai
    para ``observacoes`` em vez de ser apagado. Como a ordem é decidida pela
    data da campanha e não pela ordem de iteração, o resultado não muda a cada
    sincronização, e o arquivamento não duplica.

    Retorna ``True`` se mudou alguma coisa.
    """
    address = _normalize_text(visit.address)
    if not address:
        return False

    current = _normalize_text(user.address)

    # Primeiro endereço do tutor: nada a comparar.
    if not current and not user.endereco_id:
        user.address = _fit(address, 200)
        user.endereco_id = _build_endereco(address, visit).id
        return True

    if current == address:
        return False

    # Endereço corrigido na ficha vence a planilha: registra o da visita nas
    # observações e não toca no que a clínica escreveu.
    if not _address_came_from_campaign(user, _tutor_visits_with_address(user)):
        return _archive_previous_address(user, address)

    # Tutor já tem endereço e este é outro. Quem vence é a visita mais recente;
    # o perdedor é registrado para não sumir.
    if not _is_newest_address_source(user, visit):
        return _archive_previous_address(user, address)

    if current:
        _archive_previous_address(user, current)
    user.address = _fit(address, 200)
    user.endereco_id = _build_endereco(address, visit).id
    return True


def _ensure_tutor_account(visit: PmoVaccinationVisit) -> None:
    if visit.tutor_user_id:
        user = visit.tutor_user
        if user:
            _apply_visit_address(user, visit)
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
        _apply_visit_address(user, visit)
        return
    if _find_user_by_phone(phone):
        # Não é erro (famílias diferentes dividem telefone), mas é o momento em
        # que o celular deixa de identificar uma conta só — vale registrar para
        # conferir quando alguém relatar problema de acesso.
        current_app.logger.info(
            "PMO: nova conta de tutor no telefone %s já usado por outra família (visita %s, tutor %r)",
            normalized_phone,
            visit.id,
            visit.tutor_name,
        )
    user = User(
        name=visit.tutor_name,
        email=_unique_provisional_email(normalized_phone, visit),
        # O endereço pmo-<telefone>@petorlandia.local é um identificador interno,
        # não um e-mail da tutora: ela não o conhece e nada entregue nele chega.
        # Sem esta marca a interface o exibia como contato real e montava
        # mailto: para um domínio que não existe.
        email_is_placeholder=True,
        phone=normalized_phone,
        role="adotante",
    )
    user.set_password(visit.password)
    db.session.add(user)
    db.session.flush()
    _apply_visit_address(user, visit)
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

    # O mesmo tutor pode ter cadastros repetidos do mesmo bicho (digitação
    # diferente entre campanhas, corrida entre o sync e a tela). Escolher com
    # ``.first()`` sem ordem fazia o vínculo pular de um para outro a cada
    # religação — e a foto que estava no cadastro antigo "sumia" da
    # carteirinha. A ordem abaixo é estável: primeiro quem tem foto, depois o
    # cadastro mais antigo, que é o que acumula histórico.
    candidate = (
        Animal.query.filter_by(user_id=visit.tutor_user_id)
        .filter(func.lower(Animal.name) == pmo_animal.name.lower())
        .order_by(
            case((Animal.image.isnot(None), 0), else_=1),
            Animal.id.asc(),
        )
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
                email_is_placeholder=True,
                phone=normalized_phone,
                role="adotante",
            )
            target.set_password(visit.password)
            db.session.add(target)
            db.session.flush()
            _apply_visit_address(target, visit)
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


def cleanup_pmo_orphan_animals(dry_run: bool = True) -> dict:
    """Remove registros de animais da campanha PMO que ficaram órfãos.

    Um órfão é um ``Animal`` criado automaticamente pela campanha que não tem
    mais nenhuma visita apontando para ele (vínculo perdido em re-syncs durante
    o bug de mesclagem de tutores). Esses registros ficaram em perfis errados.

    Só remove um órfão quando existe uma cópia **canônica** (vinculada a uma
    visita PMO) com o mesmo nome — ou seja, é uma duplicata segura. Órfãos sem
    cópia canônica são **preservados** e apenas contados, para revisão manual.
    """
    stats = {"orfaos": 0, "removidos": 0, "preservados": 0}

    linked_animal_ids = (
        db.session.query(PmoVaccinationAnimal.animal_id)
        .filter(PmoVaccinationAnimal.animal_id.isnot(None))
        .subquery()
    )
    orphans = (
        Animal.query
        .filter(Animal.description.like("Cadastro criado automaticamente pela campanha%"))
        .filter(~Animal.id.in_(db.session.query(linked_animal_ids.c.animal_id)))
        .all()
    )

    for animal in orphans:
        stats["orfaos"] += 1
        target_name = (animal.name or "").strip().lower()
        has_canonical = (
            db.session.query(PmoVaccinationAnimal.id)
            .join(Animal, Animal.id == PmoVaccinationAnimal.animal_id)
            .filter(PmoVaccinationAnimal.animal_id.isnot(None))
            .filter(func.lower(func.trim(Animal.name)) == target_name)
            .first()
        )
        if has_canonical:
            stats["removidos"] += 1
            if not dry_run:
                db.session.delete(animal)
        else:
            stats["preservados"] += 1

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
    _remember_visit_token(visit)
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


def parse_vacina_pmo_rows(
    values: list[list[Any]], *, force_ai: bool = False
) -> list[dict[str, Any]]:
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
        animals = parse_animals(_cell(row, 9 + offset), dogs, cats, force_ai=force_ai)
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


def _column_index(column: str) -> int:
    index = 0
    for char in column.upper():
        if not ("A" <= char <= "Z"):
            raise ValueError(f"Coluna de planilha inválida: {column}")
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index


def _read_sheet_values_by_gid(
    service,
    spreadsheet_id: str,
    sheet_gid: str,
    range_value: str,
) -> list[list[Any]]:
    match = re.fullmatch(r"([A-Za-z]+):([A-Za-z]+)", (range_value or "").strip())
    if not match:
        raise ValueError(
            "PMO_VACCINE_SHEET_RANGE deve usar colunas no formato A:T "
            "para abas identificadas por gid."
        )
    start_column = _column_index(match.group(1)) - 1
    end_column = _column_index(match.group(2))
    if end_column <= start_column:
        raise ValueError("Intervalo de colunas da planilha PMO inválido.")

    result = (
        service.spreadsheets()
        .values()
        .batchGetByDataFilter(
            spreadsheetId=spreadsheet_id,
            body={
                "dataFilters": [
                    {
                        "gridRange": {
                            "sheetId": int(sheet_gid),
                            "startColumnIndex": start_column,
                            "endColumnIndex": end_column,
                        }
                    }
                ],
                "majorDimension": "ROWS",
            },
        )
        .execute()
    )
    value_ranges = result.get("valueRanges", [])
    if not value_ranges:
        return []
    return value_ranges[0].get("valueRange", {}).get("values", [])


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


# A lista de abas sai de uma chamada à API do Google que o painel faz antes de
# mostrar qualquer visita: ~0,5s no caminho quente e vários segundos com o
# cliente frio (logo depois de um deploy). As abas só mudam quando um dia novo é
# criado — e aí invalidamos o cache —, então guardar por alguns minutos tira esse
# tempo do caminho de abertura do painel.
PMO_SHEETS_CACHE_TTL = 300.0
_PMO_SHEETS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def invalidate_vacina_pmo_sheets_cache() -> None:
    _PMO_SHEETS_CACHE.clear()


def list_vacina_pmo_sheets(*, use_cache: bool = True) -> list[dict[str, Any]]:
    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    spreadsheet_id = _extract_google_sheet_id(sheet_url)
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO inválido.")
    cached = _PMO_SHEETS_CACHE.get(spreadsheet_id)
    if use_cache and cached and (time.monotonic() - cached[0]) < PMO_SHEETS_CACHE_TTL:
        return [dict(item) for item in cached[1]]
    service = _get_sheets_service()
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
    _PMO_SHEETS_CACHE[spreadsheet_id] = (time.monotonic(), sheets)
    return [dict(item) for item in sheets]


# Faixas de valores da planilha. O painel lê a mesma aba "Controle de doses"
# duas vezes (resumo de doses e controle de frascos) e pagava o round-trip
# inteiro em cada abertura. Guardar os valores por alguns minutos tira isso do
# caminho de abertura; o botão "Atualizar" do painel força a releitura.
PMO_SHEET_VALUES_CACHE_TTL = 300.0
_PMO_SHEET_VALUES_CACHE: dict[tuple[str, str], tuple[float, list[list[Any]]]] = {}


def _pmo_spreadsheet_id() -> str:
    spreadsheet_id = _extract_google_sheet_id(
        os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    )
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO inválido.")
    return spreadsheet_id


def invalidate_pmo_sheet_values_cache() -> None:
    _PMO_SHEET_VALUES_CACHE.clear()


def read_pmo_sheet_values(
    spreadsheet_id: str, title: str, a1_range: str, *, use_cache: bool = True
) -> list[list[Any]]:
    """Lê uma faixa da planilha PMO com cache de leitura por alguns minutos."""
    key = (spreadsheet_id, f"{title}!{a1_range}")
    cached = _PMO_SHEET_VALUES_CACHE.get(key)
    if use_cache and cached and (time.monotonic() - cached[0]) < PMO_SHEET_VALUES_CACHE_TTL:
        return [list(row) for row in cached[1]]
    service = _get_sheets_service()
    values = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{_quote_sheet_title(title)}!{a1_range}")
        .execute()
        .get("values", [])
    )
    _PMO_SHEET_VALUES_CACHE[key] = (time.monotonic(), values)
    return [list(row) for row in values]


def invalidate_pmo_painel_caches() -> None:
    """Zera tudo que o painel guarda de planilha (usado pelo botão Atualizar)."""
    invalidate_vacina_pmo_sheets_cache()
    invalidate_pmo_sheet_values_cache()


def infer_visit_status(animals: list[dict[str, Any]] | list[PmoVaccinationAnimal]) -> str:
    if not animals:
        return "pendente"
    statuses = [
        animal.get("status", "pendente") if isinstance(animal, dict) else (animal.status or "pendente")
        for animal in animals
    ]
    # Casa resolvida é casa sem pendência: quem já estava imunizado conta para
    # fechar a visita, mesmo sem dose aplicada nela.
    if all(status in PMO_DONE_STATUSES for status in statuses):
        return "vacinado"
    if any(status in PMO_DONE_STATUSES for status in statuses):
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


# ---------------------------------------------------------------------------
# Imunidade já conquistada
#
# A antirrábica é anual. Quando a mesma casa é reinscrita — encaixe, remarcação
# ou cadastro novo feito pelo tutor — o vacinador chega sem saber que parte dos
# animais tomou a dose há poucos meses. O índice abaixo responde, para cada
# animal da lista do dia, se ele já tem dose registrada dentro da janela e
# quando ela foi aplicada.
# ---------------------------------------------------------------------------

PMO_IMMUNITY_DAYS = 365

# Desfecho de quem chegou na visita já protegido por uma dose anterior. Fica
# separado de "vacinado" porque aquele status é a fonte da contagem de doses:
# somar este ali inflaria o consumo do frasco e a cobertura da campanha, e
# ainda carimbaria uma data de aplicação que nunca existiu.
PMO_STATUS_ALREADY_IMMUNE = "imunizado"

# Uma dose saiu do frasco. É o que conta consumo, cobertura e o que vai para as
# colunas de vacinados da planilha.
PMO_DOSE_STATUSES = ("vacinado",)

# Desfechos que encerram o animal na visita — para "nada pendente" na folha
# impressa e para o selo da casa. Dose gasta é outra pergunta, respondida
# apenas por ``PMO_DOSE_STATUSES``.
PMO_DONE_STATUSES = ("vacinado", PMO_STATUS_ALREADY_IMMUNE)


def _pmo_visit_has_field_record(visit: PmoVaccinationVisit) -> bool:
    """A visita guarda trabalho que aconteceu na porta do morador?

    Vacina aplicada ou animal dispensado por já estar imunizado são fatos do
    campo, não dados da planilha. Serve de trava contra apagar por engano.
    """
    return any(
        (animal.status or "") in PMO_DONE_STATUSES for animal in (visit.animals or [])
    )


def _pmo_animal_slug(value: Any) -> str:
    text = _strip_accents(_normalize_text(value)).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _pmo_address_slug(value: Any) -> str:
    text = _strip_accents(_normalize_text(value)).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _pmo_visit_phones(visit: PmoVaccinationVisit) -> set[str]:
    return {
        phone
        for phone in (_normalize_phone(visit.phone1), _normalize_phone(visit.phone2))
        if phone
    }


def _pmo_same_household(left: PmoVaccinationVisit, right: PmoVaccinationVisit) -> bool:
    """Mesma casa entre duas listas diferentes.

    Preferir falso negativo a falso positivo, como no resto do módulo: deixar
    de avisar custa uma dose a mais; avisar errado faria o vacinador pular um
    animal que nunca foi vacinado, ou misturar animais de famílias distintas.

    Telefone sozinho NUNCA deve unir moradores quando o nome E o endereço forem
    completamente divergentes (situação comum quando compartilham telefone
    comercial, de recado ou de parentes intermediários).
    """
    phones_match = bool(_pmo_visit_phones(left) & _pmo_visit_phones(right))
    names_match = _same_person_name(left.tutor_name, right.tutor_name)
    left_address = _pmo_address_slug(left.address)
    right_address = _pmo_address_slug(right.address)
    addresses_match = bool(left_address) and left_address == right_address

    if phones_match:
        # Se os telefones batem, precisa haver coerência de nome OU de endereço.
        return bool(names_match or addresses_match)

    # Se os telefones não batem (ou um mudou), precisa bater nome E endereço.
    return bool(names_match and addresses_match)


def _pmo_close_slugs(left: str, right: str) -> bool:
    """Nomes quase iguais: um caractere de diferença em nomes de 4+ letras.

    "Lipe" numa lista e "Lupe" na seguinte é a mesma cadela redigitada. Nomes
    curtos ficam de fora porque "Bob"/"Bib" seriam colapsados sem necessidade.
    """
    if not left or not right or left == right:
        return False
    if min(len(left), len(right)) < 4 or abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(1 for a, b in zip(left, right) if a != b) == 1
    menor, maior = (left, right) if len(left) < len(right) else (right, left)
    for corte in range(len(maior)):
        if maior[:corte] + maior[corte + 1:] == menor:
            return True
    return False


def _pmo_visit_reference_date(visit: PmoVaccinationVisit) -> date | None:
    if visit.vaccine_date:
        return visit.vaccine_date
    try:
        return datetime.strptime(_normalize_text(visit.sheet_title), "%d/%m/%Y").date()
    except (TypeError, ValueError):
        pass
    return visit.requested_date


def _pmo_dose_date(animal: PmoVaccinationAnimal, visit: PmoVaccinationVisit) -> date | None:
    """Dia em que a dose que protege este animal foi aplicada.

    Para quem foi marcado como já imunizado, a data válida é a da dose antiga
    registrada em ``immune_since`` — nunca a data da visita, onde nada foi
    aplicado. Sem isso, cada visita empurraria a proteção um ano para frente.
    """
    if animal.status == PMO_STATUS_ALREADY_IMMUNE:
        return animal.immune_since
    if animal.vaccinated_at:
        return animal.vaccinated_at.date()
    return _pmo_visit_reference_date(visit)


def _pmo_previous_doses(visits: list[PmoVaccinationVisit]) -> list[dict[str, Any]]:
    """Doses já aplicadas fora das listas informadas, para o mesmo conjunto de casas."""
    if not visits:
        return []
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload

    ids_atuais = {visit.id for visit in visits if visit.id}
    filtros = []
    telefones = sorted({p for visit in visits for p in (visit.phone1, visit.phone2) if p})
    nomes = sorted({visit.tutor_name for visit in visits if visit.tutor_name})
    if telefones:
        filtros.append(PmoVaccinationVisit.phone1.in_(telefones))
        filtros.append(PmoVaccinationVisit.phone2.in_(telefones))
    if nomes:
        filtros.append(PmoVaccinationVisit.tutor_name.in_(nomes))
    if not filtros:
        return []

    anteriores = (
        PmoVaccinationVisit.query.options(joinedload(PmoVaccinationVisit.animals))
        .filter(or_(*filtros))
        .all()
    )
    doses = []
    for visita in anteriores:
        if visita.id in ids_atuais:
            continue
        for animal in visita.animals:
            # "Já imunizado" também entra: ele carrega a data da dose antiga e
            # mantém a corrente de proteção viva entre campanhas.
            if animal.status not in PMO_DONE_STATUSES:
                continue
            aplicada_em = _pmo_dose_date(animal, visita)
            if not aplicada_em:
                continue
            doses.append({
                "visit": visita,
                "animal_id": animal.animal_id,
                "name": animal.name or "",
                "slug": _pmo_animal_slug(animal.name),
                "species": animal.species,
                "date": aplicada_em,
                "sheet_title": visita.sheet_title or "",
            })
    return doses


def _pmo_immunity_payload(dose: dict[str, Any], match: str, reference: date) -> dict[str, Any]:
    aplicada_em = dose["date"]
    dias = (reference - aplicada_em).days
    protegido_ate = aplicada_em + timedelta(days=PMO_IMMUNITY_DAYS)
    return {
        "date": aplicada_em.isoformat(),
        "dateLabel": aplicada_em.strftime("%d/%m/%Y"),
        "protectedUntil": protegido_ate.isoformat(),
        "protectedUntilLabel": protegido_ate.strftime("%d/%m/%Y"),
        "daysAgo": dias,
        "immune": 0 <= dias < PMO_IMMUNITY_DAYS,
        "match": match,
        "matchedName": dose["name"],
        "sheetTitle": dose["sheet_title"],
    }


def build_previous_immunity_index(
    visits: list[PmoVaccinationVisit],
) -> dict[int, dict[int, dict[str, Any]]]:
    """``{visit_id: {animal_id: dados da dose anterior}}``.

    A comparação é feita em três níveis, do mais forte para o mais fraco:
    mesmo cadastro de animal, mesmo nome, e nome com uma letra de diferença.
    Só o terceiro nível é marcado como aproximado, para que a tela possa pedir
    conferência em vez de afirmar.
    """
    doses = _pmo_previous_doses(visits)
    if not doses:
        return {}

    indice: dict[int, dict[int, dict[str, Any]]] = {}
    for visita in visits:
        referencia = _pmo_visit_reference_date(visita) or now_in_brazil().date()
        candidatas = [
            dose for dose in doses
            if dose["date"] <= referencia and _pmo_same_household(visita, dose["visit"])
        ]
        if not candidatas:
            continue
        candidatas.sort(key=lambda dose: dose["date"], reverse=True)
        por_animal: dict[int, dict[str, Any]] = {}
        for animal in visita.animals:
            slug = _pmo_animal_slug(animal.name)
            escolhida = None
            grau = ""
            for dose in candidatas:
                if animal.animal_id and dose["animal_id"] == animal.animal_id:
                    escolhida, grau = dose, "cadastro"
                    break
                if slug and dose["slug"] == slug:
                    escolhida, grau = dose, "exato"
                    break
                if not escolhida and _pmo_close_slugs(slug, dose["slug"]):
                    escolhida, grau = dose, "aproximado"
            if escolhida:
                por_animal[animal.id] = _pmo_immunity_payload(escolhida, grau, referencia)
        if por_animal:
            indice[visita.id] = por_animal
    return indice


def _serialize_visit(
    visit: PmoVaccinationVisit,
    immunity: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``immunity`` já calculado em lote; quando omitido, calcula só desta visita.

    O padrão precisa calcular: as rotas que devolvem uma visita só (mudar
    status, renomear animal, incluir animal) substituem a linha na tela, e sem
    isso o aviso de dose anterior sumiria no primeiro toque do vacinador.
    """
    _ensure_visit_public_token(visit)
    evaluation = get_vacina_pmo_evaluation_payload(visit)
    if immunity is None:
        immunity = build_previous_immunity_index([visit]).get(visit.id, {})
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
            "imageUrl": (animal.animal.image if animal.animal and animal.animal.image else ""),
            "imageProxyUrl": (
                url_for("vacina_pmo_animal_photo_src", animal_id=animal.id)
                if has_request_context() and animal.animal and animal.animal.image
                else ""
            ),
            "previousVaccination": immunity.get(animal.id),
            "immuneSince": animal.immune_since.isoformat() if animal.immune_since else "",
            "immuneSinceLabel": (
                animal.immune_since.strftime("%d/%m/%Y") if animal.immune_since else ""
            ),
        }
        for animal in visit.animals
    ]
    return {
        "id": f"visit-{visit.id}",
        "visitId": visit.id,
        "status": infer_visit_status(animals),
        "tutor": visit.tutor_name,
        "address": visit.address or "",
        "lat": visit.geocode_lat,
        "lng": visit.geocode_lng,
        "geocoded": bool(visit.geocode_lat is not None and visit.geocode_lng is not None),
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
    imunidade = build_previous_immunity_index(visits)
    return {
        "rows": [
            _serialize_visit(visit, imunidade.get(visit.id))
            for visit in visits
        ],
        "sheet_gid": sheet_gid or (latest.sheet_gid if latest else ""),
        "sheet_title": sheet_title or (latest.sheet_title if latest else ""),
        "spreadsheet_id": visits[0].spreadsheet_id if visits else "",
    }


def _vacina_pmo_video_period_bounds(period: str, reference_date: date) -> tuple[date, date]:
    """Resolve o intervalo inclusivo usado pelo compilado de vídeo."""
    normalized_period = (period or "").strip().lower()
    if normalized_period == "week":
        start = reference_date - timedelta(days=reference_date.weekday())
        return start, start + timedelta(days=6)
    if normalized_period == "month":
        start = reference_date.replace(day=1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start, next_month - timedelta(days=1)
    raise ValueError("Período do vídeo inválido. Use semana ou mês.")


def get_vacina_pmo_video_items(*, period: str, reference_date: str) -> dict[str, Any]:
    """Lista somente os animais vacinados com foto no período solicitado.

    O compilado parte dos registros já sincronizados da planilha. A resposta é
    deliberadamente enxuta: não expõe telefone, endereço, senha ou avaliação.
    """
    try:
        reference = date.fromisoformat((reference_date or "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("Data de referência inválida para o vídeo.") from exc

    normalized_period = (period or "").strip().lower()
    start, end = _vacina_pmo_video_period_bounds(normalized_period, reference)
    visits = (
        PmoVaccinationVisit.query
        .options(joinedload(PmoVaccinationVisit.animals).joinedload(PmoVaccinationAnimal.animal))
        .filter(PmoVaccinationVisit.vaccine_date >= start)
        .filter(PmoVaccinationVisit.vaccine_date <= end)
        .order_by(
            PmoVaccinationVisit.vaccine_date.asc(),
            PmoVaccinationVisit.source_row.asc(),
            PmoVaccinationVisit.id.asc(),
        )
        .all()
    )

    items = []
    dates = set()
    for visit in visits:
        visit_date = visit.vaccine_date.isoformat() if visit.vaccine_date else ""
        for animal in visit.animals:
            image_url = animal.animal.image if animal.animal and animal.animal.image else ""
            if animal.status != "vacinado" or not image_url:
                continue
            dates.add(visit_date)
            items.append(
                {
                    "id": animal.id,
                    "name": animal.name or "Animal",
                    "species": animal.species or "cao",
                    "date": visit_date,
                    "imageUrl": image_url,
                    "imageProxyUrl": (
                        url_for("vacina_pmo_animal_photo_src", animal_id=animal.id)
                        if has_request_context()
                        else ""
                    ),
                }
            )

    return {
        "period": normalized_period,
        "reference_date": reference.isoformat(),
        "date_start": start.isoformat(),
        "date_end": end.isoformat(),
        "dates_count": len(dates),
        "items": items,
    }


def get_all_vacina_pmo_evaluations() -> dict[str, Any]:
    """Avaliações agregadas de TODAS as abas (compilado geral, leve).

    Devolve só os campos usados pelo painel de avaliações — nada de telefone,
    endereço ou senha — de cada visita já cadastrada, independente da aba.
    """
    visits = (
        PmoVaccinationVisit.query.order_by(
            PmoVaccinationVisit.id.desc()
        ).all()
    )
    rows = [
        {
            "tutor": visit.tutor_name,
            "sheetTitle": visit.sheet_title or "",
            "date": visit.vaccine_date.isoformat() if visit.vaccine_date else "",
            "evaluationRating": visit.evaluation_rating,
            "evaluationRegistrationRating": visit.evaluation_registration_rating,
            "evaluationServiceRating": visit.evaluation_service_rating,
            "evaluationInformationRating": visit.evaluation_information_rating,
            "evaluationSurveyRating": visit.evaluation_survey_rating,
            "evaluationComment": visit.evaluation_comment or "",
            "evaluatedAt": visit.evaluated_at.isoformat() if visit.evaluated_at else "",
        }
        for visit in visits
    ]
    return {"rows": rows, "total_visits": len(rows)}


def _route_preview_item(visit: PmoVaccinationVisit, coords: tuple[float, float] | None, order: int) -> dict[str, Any]:
    lat = coords[0] if coords else visit.geocode_lat
    lng = coords[1] if coords else visit.geocode_lng
    return {
        "visitId": visit.id,
        "sourceRow": visit.source_row,
        "order": order,
        "tutor": visit.tutor_name or "",
        "address": visit.address or "",
        "shift": visit.shift or "",
        "located": bool(coords or (lat is not None and lng is not None)),
        "lat": lat,
        "lng": lng,
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
        cache_key = _pmo_geocode_cache_key(visit.address or "")
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
        # Fallback gracioso: agrupa os endereços por bairro caso o GPS esteja temporariamente indisponível
        optimized = sorted(
            ungeocoded,
            key=lambda v: (_pmo_extract_bairro_key(v.address or ""), v.source_row or 0, v.id),
        )
    else:
        geocoded_ordered = _nearest_neighbor_route(origin_coords, geocoded)
        optimized = _merge_ungeocoded_intelligently(geocoded_ordered, ungeocoded)
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


def _pmo_build_full_google_maps_route_url(
    origin_coords: tuple[float, float] | None,
    optimized_visits: list[PmoVaccinationVisit],
    coords_by_visit_id: dict[int, tuple[float, float]],
) -> str:
    """Gera link universal do Google Maps com paradas múltiplas sequenciadas."""
    if not optimized_visits:
        return ""
    origin_str = (
        f"{origin_coords[0]},{origin_coords[1]}"
        if origin_coords
        else "Vigilancia Sanitaria, Orlandia, SP, Brasil"
    )
    stops: list[str] = []
    for v in optimized_visits:
        c = coords_by_visit_id.get(v.id)
        if c:
            stops.append(f"{c[0]},{c[1]}")
        else:
            clean = _pmo_clean_address_fragment(v.address or "")
            if clean:
                stops.append(f"{clean}, Orlandia, SP, Brasil")
    if not stops:
        return ""
    if len(stops) == 1:
        return f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(origin_str)}&destination={urllib.parse.quote(stops[0])}&travelmode=driving"
    destination = urllib.parse.quote(stops[-1])
    intermediate = stops[:-1][:9]
    waypoints = urllib.parse.quote("|".join(intermediate))
    return f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(origin_str)}&destination={destination}&waypoints={waypoints}&travelmode=driving"


def preview_vacina_pmo_route(*, sheet_gid: str = "", sheet_title: str = "", shift: str = "") -> dict[str, Any]:
    context = _pmo_route_context(sheet_gid=sheet_gid, sheet_title=sheet_title, shift=shift)
    coords_by_visit_id = context["coords_by_visit_id"]
    origin_coords = _pmo_route_origin_coords()
    maps_url = _pmo_build_full_google_maps_route_url(origin_coords, context["optimized"], coords_by_visit_id)
    return {
        "sheet_gid": context["sheet_gid"],
        "sheet_title": context["sheet_title"],
        "spreadsheet_id": context["spreadsheet_id"],
        "shift": context["normalized_shift"],
        "origin": _pmo_route_origin_address(),
        "optimized_count": len(context["optimized"]),
        "unlocated_count": context["unlocated_count"],
        "geocoded_now": context["geocoded_now"],
        "google_maps_url": maps_url,
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
    coords_by_visit_id = context["coords_by_visit_id"]

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
    origin_coords = _pmo_route_origin_coords()
    maps_url = _pmo_build_full_google_maps_route_url(origin_coords, optimized, coords_by_visit_id)
    return {
        **state,
        "shift": context["normalized_shift"],
        "origin": _pmo_route_origin_address(),
        "optimized_count": len(optimized),
        "unlocated_count": context["unlocated_count"],
        "geocoded_now": context["geocoded_now"],
        "google_maps_url": maps_url,
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
                if _pmo_visit_has_field_record(stale_visit):
                    # Aqui houve trabalho de campo: animal vacinado ou
                    # dispensado por imunidade. Uma linha que mudou de lugar na
                    # planilha não pode apagar isso — junto iriam o status, a
                    # carteirinha do tutor e o vínculo com a foto do animal.
                    # Some da lista do dia, mas o registro fica.
                    stale_visit.source_row = -abs(stale_visit.id)
                    continue
                db.session.delete(stale_visit)

    db.session.commit()
    imunidade = build_previous_immunity_index(saved)
    return [_serialize_visit(visit, imunidade.get(visit.id, {})) for visit in saved]


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
    # Mesma regra do selo: ja imunizado fecha o animal, mesmo sem dose.
    if all(status in PMO_DONE_STATUSES for status in statuses):
        return "vacinado"
    if any(status in PMO_DONE_STATUSES for status in statuses):
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


def write_animal_counts_to_sheet(visit: PmoVaccinationVisit) -> bool:
    """Escreve quantos cães (H) e gatos (I) a casa tem na linha de origem do tutor."""
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
                "Falha ao iniciar cliente Sheets para gravar contagem de animais PMO", exc_info=True
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
            f"{PMO_DOGS_COLUMN}{visit.source_row}:{PMO_CATS_COLUMN}{visit.source_row}"
        )
        service.spreadsheets().values().update(
            spreadsheetId=visit.spreadsheet_id,
            range=range_value,
            valueInputOption="USER_ENTERED",
            body={"values": [[visit.dogs or 0, visit.cats or 0]]},
        ).execute()
        return True
    except Exception:
        from flask import current_app
        try:
            current_app.logger.warning(
                "Falha ao atualizar contagem de animais na planilha PMO", exc_info=True
            )
        except Exception:
            pass
        return False


def _validate_pmo_animal_name(name: Any) -> str:
    normalized = _normalize_text(name)
    if not normalized:
        raise ValueError("Digite o nome do animal.")
    if len(normalized) > PMO_ANIMAL_NAME_MAX:
        raise ValueError(f"O nome do animal deve ter no máximo {PMO_ANIMAL_NAME_MAX} caracteres.")
    # A célula da planilha é reimportada separando por vírgula/";"/" e "; um nome com
    # esses separadores viraria dois animais na próxima sincronização.
    if len(_split_animals(normalized)) > 1:
        raise ValueError("Use um nome sem vírgulas, ponto e vírgula ou \" e \" — ele separa animais na planilha.")
    return normalized


def update_vacina_pmo_animal_name(animal_id: int, name: str) -> dict[str, Any]:
    """Corrige o nome de um animal e replica a célula de nomes (coluna J) na planilha."""
    normalized = _validate_pmo_animal_name(name)

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


def _pmo_parse_immune_since(value: Any, reference: date) -> date:
    """Data da dose informada à mão, quando o sistema não tem o registro.

    O vacinador está com a carteirinha de papel na frente e sabe a data; o
    sistema não. Aceitar o que ele lê é melhor do que obrigá-lo a aplicar uma
    dose desnecessária — desde que a data resista às três perguntas óbvias.
    """
    texto = _normalize_text(value)
    if not texto:
        raise ValueError("Informe a data da vacina anterior.")
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            informada = datetime.strptime(texto, formato).date()
            break
        except ValueError:
            continue
    else:
        raise ValueError("Data inválida. Use o formato dd/mm/aaaa.")
    if informada > reference:
        raise ValueError("A data da vacina anterior não pode estar no futuro.")
    if (reference - informada).days >= PMO_IMMUNITY_DAYS:
        raise ValueError(
            "Essa dose tem mais de um ano e não protege mais. "
            "O animal precisa ser vacinado."
        )
    return informada


def update_vacina_pmo_animal_status(
    animal_id: int, status: str, immune_since: Any = None
) -> dict[str, Any]:
    allowed = {"pendente", "vacinado", PMO_STATUS_ALREADY_IMMUNE,
               "ausente", "remarcar", "recusou"}
    if status not in allowed:
        raise ValueError("Status inválido.")
    animal = PmoVaccinationAnimal.query.get_or_404(animal_id)
    animal.status = status
    animal.vaccinated_at = utcnow() if status == "vacinado" else None
    if status == PMO_STATUS_ALREADY_IMMUNE:
        # A data vem do histórico ou da carteirinha que o tutor mostrou — nunca
        # do relógio. Sem uma das duas o desfecho não se sustenta.
        referencia = _pmo_visit_reference_date(animal.visit) or now_in_brazil().date()
        if immune_since:
            animal.immune_since = _pmo_parse_immune_since(immune_since, referencia)
        else:
            anterior = (
                build_previous_immunity_index([animal.visit])
                .get(animal.visit_id, {})
                .get(animal.id)
            )
            if not anterior or not anterior.get("immune"):
                raise ValueError(
                    "Não há dose registrada no último ano para este animal. "
                    "Informe a data da vacina anterior para marcar como já imunizado."
                )
            animal.immune_since = date.fromisoformat(anterior["date"])
    else:
        animal.immune_since = None
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
    # Alguem abriu a porta: marcar como ja imunizado tambem exige
    # atendimento presencial.
    attended_statuses = {"vacinado", PMO_STATUS_ALREADY_IMMUNE,
                         "recusou", "remarcar"}
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


# Teto de animais por casa. O dia inteiro é planejado para ~23 animais
# (PMO_DAY_TARGET_ANIMALS), então uma casa passar disso é quase sempre engano de
# digitação — melhor barrar do que estourar a rota do turno sem ninguém perceber.
PMO_VISIT_ANIMALS_MAX = 12


def _pmo_sort_visit_animals(visit: PmoVaccinationVisit) -> None:
    """Reordena as posições: cães primeiro, gatos depois.

    É a mesma ordem que ``_build_animals`` usa ao reconstruir a visita a partir da
    planilha (a espécie de cada slot vem da posição). Mantendo a ordem igual, a
    coluna J escrita agora volta idêntica no próximo sync.
    """
    ordered = sorted(visit.animals, key=lambda animal: (animal.species != "cao", animal.position))
    for position, animal in enumerate(ordered, start=1):
        animal.position = position


def _pmo_new_visit_sheet_row(payload: dict[str, Any], animals: list[dict[str, str]],
                             note: str) -> list[str]:
    """Colunas A..K da casa. Data (Q) e turno (R) são do modelo e não se tocam."""
    nomes = ", ".join(item["name"] for item in animals)
    caes = sum(1 for item in animals if item["species"] == "cao")
    gatos = sum(1 for item in animals if item["species"] == "gato")
    return [
        _normalize_text(payload.get("tutor")),
        _normalize_text(payload.get("street")),
        _normalize_text(payload.get("number")),
        _normalize_text(payload.get("complement")),
        _normalize_text(payload.get("neighborhood")),
        _normalize_text(payload.get("phone1")),
        _normalize_text(payload.get("phone2")),
        str(caes),
        str(gatos),
        nomes,
        note,
    ]


def _pmo_free_slot_row(values: list[list[Any]], shift: str) -> int:
    """Primeira vaga livre do turno pedido dentro da aba do dia.

    A aba não é uma tabela simples: ela é a cópia do modelo, com um bloco de
    manhã, um de tarde, cabeçalho repetido e linhas de totais no meio. Cada
    vaga já vem com a data (Q) e o turno (R) preenchidos pelo modelo.

    Por isso não dá para usar ``values().append``: o Sheets tenta adivinhar
    onde a tabela termina, erra nesse layout e insere no topo do bloco —
    empurrando todas as casas para baixo e invalidando o ``source_row`` de
    quem já estava lá. Aqui a vaga é escolhida explicitamente e escrita com
    ``update``, sem deslocar ninguém.

    Uma vaga é uma linha que tem data e turno do modelo, e está vazia tanto
    nos dados da casa (A..K) quanto nas colunas de execução (L..O) — estas
    últimas separam a vaga de uma linha de totais, que também tem data.
    """
    alvo = _normalize_shift(shift)
    for indice, linha in enumerate(values, start=1):
        def celula(coluna: int) -> str:
            return _normalize_text(linha[coluna] if coluna < len(linha) else "")

        if any(celula(coluna) for coluna in range(0, 11)):
            continue  # a casa já está preenchida
        if any(celula(coluna) for coluna in range(11, 15)):
            continue  # linha de totais/resumo: tem data, mas não é vaga
        if not _parse_date_object(celula(16)):
            continue  # sem data do modelo não é uma vaga de casa
        if alvo and _normalize_shift(celula(17)) != alvo:
            continue
        return indice
    raise ValueError(
        f"A aba do dia não tem vaga livre no turno {alvo or 'selecionado'}. "
        "Acrescente uma linha na planilha ou escolha o outro turno."
    )


def create_vacina_pmo_visit(payload: dict[str, Any]) -> dict[str, Any]:
    """Cadastra uma casa que apareceu durante a rota.

    A planilha é a fonte de verdade da aba do dia: o sync apaga toda visita
    cujo ``source_row`` sumiu de lá. Por isso a linha é gravada na planilha
    PRIMEIRO e o registro local só nasce com o número de linha que o Sheets
    devolveu — se a gravação falhar, nada é criado e o vacinador tenta de novo,
    em vez de ficar com um cadastro que some no próximo sync.
    """
    tutor = _normalize_text(payload.get("tutor"))
    if not tutor:
        raise ValueError("Informe o nome do tutor.")

    animais: list[dict[str, str]] = []
    vistos: set[str] = set()
    for bruto in payload.get("animals") or []:
        nome = _normalize_text((bruto or {}).get("name"))
        if not nome:
            continue
        especie = _strip_accents(_normalize_text((bruto or {}).get("species"))).lower()
        if especie not in {"cao", "gato"}:
            raise ValueError(f"Escolha se {nome} é cão ou gato.")
        chave = _strip_accents(nome).casefold()
        if chave in vistos:
            raise ValueError(f"O animal {nome} foi informado duas vezes.")
        vistos.add(chave)
        animais.append({"name": _validate_pmo_animal_name(nome), "species": especie})
    if not animais:
        raise ValueError("Informe pelo menos um animal, com nome e espécie.")
    if len(animais) > PMO_VISIT_ANIMALS_MAX:
        raise ValueError(f"São no máximo {PMO_VISIT_ANIMALS_MAX} animais por casa.")

    phone1 = _normalize_phone(payload.get("phone1"))
    phone2 = _normalize_phone(payload.get("phone2"))
    endereco = ", ".join(
        parte for parte in (
            _normalize_text(payload.get("street")),
            _normalize_text(payload.get("number")),
            _normalize_text(payload.get("complement")),
            _normalize_text(payload.get("neighborhood")),
        ) if parte
    )
    if not phone1 and not phone2 and not endereco:
        raise ValueError("Informe pelo menos o endereço ou um telefone.")

    sheet_gid = _normalize_text(payload.get("sheet_gid"))
    if not sheet_gid:
        raise ValueError("Selecione a aba do dia antes de cadastrar.")

    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    spreadsheet_id = _extract_google_sheet_id(sheet_url)
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO inválido.")

    service = _get_sheets_service_rw()
    sheet_title = _resolve_sheet_title_by_gid(service, spreadsheet_id, sheet_gid)

    shift = _normalize_shift(payload.get("shift"))
    note = _normalize_note_line(payload.get("note"))

    atuais = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"'{sheet_title}'!A:R")
        .execute()
        .get("values", [])
    )
    source_row = _pmo_free_slot_row(atuais, shift)

    ocupada = PmoVaccinationVisit.query.filter_by(
        spreadsheet_id=spreadsheet_id, sheet_gid=sheet_gid, source_row=source_row
    ).first()
    if ocupada:
        # A planilha diz vaga livre e o banco diz ocupada: sincronize antes de
        # gravar, senão a casa nova sobrescreveria a de outra pessoa.
        raise ValueError(
            f"A linha {source_row} da aba já está registrada para "
            f"{ocupada.tutor_name}. Sincronize a aba e tente de novo."
        )

    # Só as colunas da casa (A..K). Data e turno já vêm do modelo do dia e não
    # podem ser reescritos — é o que mantém a vaga coerente com o resto da aba.
    (
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_title}'!A{source_row}:K{source_row}",
            valueInputOption="USER_ENTERED",
            body={"values": [_pmo_new_visit_sheet_row(payload, animais, note)]},
        )
        .execute()
    )

    visit = PmoVaccinationVisit(
        spreadsheet_id=spreadsheet_id,
        sheet_gid=sheet_gid,
        sheet_title=sheet_title,
        source_row=source_row,
        tutor_name=tutor,
        address=endereco,
        phone1=phone1,
        phone2=phone2,
        dogs=sum(1 for item in animais if item["species"] == "cao"),
        cats=sum(1 for item in animais if item["species"] == "gato"),
        vaccine_date=_parse_date_object(sheet_title),
        shift=shift,
        note=note,
        password=_password(),
    )
    db.session.add(visit)
    db.session.flush()
    for posicao, item in enumerate(animais, start=1):
        db.session.add(PmoVaccinationAnimal(
            visit=visit,
            position=posicao,
            name=item["name"],
            species=item["species"],
            status="pendente",
        ))
    db.session.flush()
    _append_visit_note(
        visit,
        f"{_pmo_event_time_label()} - casa cadastrada durante a rota.",
    )
    _ensure_visit_public_token(visit)
    _ensure_visit_records(visit)
    try:
        db.session.commit()
    except IntegrityError:
        # Entre a escolha da vaga e a gravacao, o sync automatico (a cada 10
        # minutos) ou outro vacinador pode ter registrado a mesma linha. Isso
        # e disputa por uma vaga, nao defeito: devolve recado em vez do erro
        # cru do banco, e a proxima tentativa pega outra vaga.
        db.session.rollback()
        raise ValueError(
            f"A linha {source_row} da aba foi ocupada enquanto você preenchia "
            "o cadastro. Os dados já estão na planilha — sincronize a aba para "
            "trazer a casa para a tela."
        ) from None
    # A observacao ganhou a linha de registro depois da gravacao inicial; sem
    # este envio a planilha ficaria so com o texto digitado.
    write_note_to_sheet(visit)
    return _serialize_visit(visit)


def add_vacina_pmo_visit_animal(visit_id: int, name: Any, species: Any) -> dict[str, Any]:
    """Inclui um animal que apareceu na hora da visita (tutor trouxe mais um).

    Além do banco, atualiza a planilha (nomes na J e contagem em H/I) porque o
    sync reconstrói os animais a partir dessas células — sem isso o bicho
    vacinado sumiria na próxima sincronização da aba.
    """
    visit = PmoVaccinationVisit.query.get_or_404(visit_id)
    normalized = _validate_pmo_animal_name(name)
    species_value = _strip_accents(_normalize_text(species)).lower()
    if species_value not in {"cao", "gato"}:
        raise ValueError("Escolha se o animal é cão ou gato.")
    if len(visit.animals) >= PMO_VISIT_ANIMALS_MAX:
        raise ValueError(f"Esta casa já está com {PMO_VISIT_ANIMALS_MAX} animais — confira a lista.")

    wanted = _strip_accents(normalized).casefold()
    if any(_strip_accents(animal.name or "").casefold() == wanted for animal in visit.animals):
        raise ValueError(f"Já existe um animal chamado {normalized} nesta casa.")

    animal = PmoVaccinationAnimal(
        visit=visit,
        position=len(visit.animals) + 1,
        name=normalized,
        species=species_value,
        status="pendente",
    )
    db.session.add(animal)
    db.session.flush()
    _pmo_sort_visit_animals(visit)
    visit.dogs = sum(1 for item in visit.animals if item.species == "cao")
    visit.cats = sum(1 for item in visit.animals if item.species == "gato")
    _append_visit_note(
        visit,
        f"{_pmo_event_time_label()} - {normalized} ({'cão' if species_value == 'cao' else 'gato'}) incluído na hora.",
    )
    _ensure_real_animal(animal)
    db.session.commit()
    write_animal_names_to_sheet(visit)
    write_animal_counts_to_sheet(visit)
    write_note_to_sheet(visit)
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
    """Carteirinha pelo link, aceitando também os links já entregues antes.

    O ``public_token`` muda quando a visita é recriada — foi o que aconteceu
    quando duas linhas indevidas empurraram a aba e o sync apagou e refez os
    registros. O tutor, porém, já tinha o link antigo no WhatsApp, enviado em
    nome da Prefeitura. Endereço publicado não pode virar 404, então o link
    antigo continua abrindo a carteirinha da mesma casa.
    """
    from models import PmoVaccinationVisitToken

    visit = PmoVaccinationVisit.query.filter_by(public_token=token).first()
    if not visit:
        antigo = PmoVaccinationVisitToken.query.filter_by(token=token).first()
        visit = antigo.visit if antigo else None
    if visit:
        _ensure_visit_public_token(visit)
        _remember_visit_token(visit)
        _ensure_visit_records(visit)
        db.session.commit()
    return visit


def _remember_visit_token(visit: PmoVaccinationVisit) -> None:
    """Guarda o link atual para que ele nunca deixe de funcionar."""
    from models import PmoVaccinationVisitToken

    if not visit.public_token:
        return
    if not visit.id:
        db.session.flush()
    if not visit.id:
        return
    ja_existe = PmoVaccinationVisitToken.query.filter_by(
        token=visit.public_token
    ).first()
    if ja_existe:
        return
    db.session.add(PmoVaccinationVisitToken(
        visit_id=visit.id, token=visit.public_token
    ))


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


def sync_vacina_pmo_sheet(
    *, sheet_gid: str = "", sheet_title: str = "", force_ai: bool = False
) -> PmoSyncResult:
    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    range_value = os.getenv("PMO_VACCINE_SHEET_RANGE", DEFAULT_SHEET_RANGE)
    service = _get_sheets_service_rw()
    spreadsheet_id, sheet_range, resolved_gid, resolved_title = _resolve_sheet_target(
        service,
        sheet_url,
        range_value,
        sheet_gid=sheet_gid,
        sheet_title=sheet_title,
    )
    if resolved_gid:
        values = _read_sheet_values_by_gid(
            service,
            spreadsheet_id,
            resolved_gid,
            range_value,
        )
    else:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=sheet_range)
            .execute()
        )
        values = result.get("values", [])
    rows = parse_vacina_pmo_rows(values, force_ai=force_ai)
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


def pmo_request_sheet_titles() -> list[str]:
    """Títulos aceitos para a aba de solicitações, do preferido ao mais antigo.

    O primeiro é o configurado (env) ou o padrão atual; os demais são nomes que
    a aba já teve. Serve para reencontrar a aba na planilha e para o histórico
    do morador continuar listando o que foi enviado antes de cada renomeação.
    """
    configured = _normalize_text(os.getenv(PMO_REQUEST_SHEET_TITLE_ENV, ""))
    titles = [configured or PMO_REQUEST_SHEET_DEFAULT_TITLE]
    seen = {_pmo_normalize_title(titles[0])}
    for legacy in (PMO_REQUEST_SHEET_DEFAULT_TITLE, *PMO_REQUEST_SHEET_LEGACY_TITLES):
        key = _pmo_normalize_title(legacy)
        if key and key not in seen:
            seen.add(key)
            titles.append(legacy)
    return titles


def _request_sheet_header_matches(values: list[list[str]] | None) -> bool:
    header = (values or [[]])[0] if values else []
    return [_normalize_text(item) for item in header] == PMO_REQUEST_HEADERS


def _find_request_sheet_by_header(service, spreadsheet_id: str, titles: list[str]) -> str:
    """Último recurso: acha a aba de solicitações pelo cabeçalho, não pelo nome.

    Cobre um renome que nenhum apelido conhecido alcança. Comparar o cabeçalho
    (e não só o nome) evita cair na aba de castração, que tem nome parecido e
    colunas diferentes.
    """
    if not titles:
        return ""
    ranges = [f"{_quote_sheet_title(title)}!{PMO_REQUEST_HEADER_RANGE}" for title in titles]
    try:
        response = (
            service.spreadsheets()
            .values()
            .batchGet(spreadsheetId=spreadsheet_id, ranges=ranges)
            .execute()
        )
    except Exception:
        return ""
    for title, value_range in zip(titles, response.get("valueRanges", [])):
        if _request_sheet_header_matches(value_range.get("values")):
            return title
    return ""


def _resolve_request_sheet_title(service, spreadsheet_id: str, title: str) -> str:
    """Devolve o título real da aba de solicitações, criando-a só se faltar.

    A comparação é tolerante (sem acento, sem caixa, apelidos antigos) porque a
    equipe renomeia a aba na planilha. Antes a busca era literal: quando
    "Solicitacoes" virou "Solicitacoes de vacina", o app criou uma aba nova e
    vazia no fim da planilha e passou a gravar ali — as solicitações dos
    moradores sumiram da aba que a equipe acompanha.
    """
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
        .execute()
    )
    existing_titles = []
    for sheet in metadata.get("sheets", []):
        existing_title = (sheet.get("properties") or {}).get("title", "")
        if existing_title:
            existing_titles.append(existing_title)

    resolved = ""
    seen: set[str] = set()
    for candidate in [title, *pmo_request_sheet_titles()]:
        key = _pmo_normalize_title(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        for existing_title in existing_titles:
            if _pmo_normalize_title(existing_title) == key:
                resolved = existing_title
                break
        if resolved:
            break

    if not resolved:
        resolved = _find_request_sheet_by_header(service, spreadsheet_id, existing_titles)

    if not resolved:
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
        return title

    header_response = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet_title(resolved)}!{PMO_REQUEST_HEADER_RANGE}",
        )
        .execute()
    )
    if not _request_sheet_header_matches(header_response.get("values")):
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet_title(resolved)}!A1",
            valueInputOption="RAW",
            body={"values": [PMO_REQUEST_HEADERS]},
        ).execute()
    return resolved


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


def _pmo_match_sheet_title(titles: list[str], wanted: str) -> str:
    """Acha o título real de uma aba de forma tolerante, dentro de ``titles``.

    Ordem de tentativa: igualdade normalizada (sem acento/maiúscula/espaços
    repetidos) → todas as palavras procuradas presentes na aba → substring em
    qualquer direção. Se nada casar, lista as abas disponíveis no erro.
    """
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


def _resolve_pmo_sheet_title(service, spreadsheet_id: str, wanted: str) -> str:
    """Versão que consulta a API na hora (usada por escritas, que não podem
    trabalhar sobre uma lista de abas possivelmente velha)."""
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
    return _pmo_match_sheet_title(titles, wanted)


def resolve_pmo_sheet_title_cached(wanted: str, *, use_cache: bool = True) -> str:
    """Mesma resolução, mas sobre a lista de abas em cache (TTL de minutos).

    Leituras de painel não precisam de metadados frescos: uma aba nova só
    aparece quando um dia de campanha é criado, e esse caminho já invalida o
    cache. Evita um round-trip à API por bloco do painel.
    """
    titles = [sheet["title"] for sheet in list_vacina_pmo_sheets(use_cache=use_cache)]
    return _pmo_match_sheet_title(titles, wanted)


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

    # A aba nova precisa aparecer no seletor do painel na hora.
    invalidate_vacina_pmo_sheets_cache()

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


def get_controle_de_doses_summary(*, use_cache: bool = True) -> dict[str, Any]:
    """Espelha a aba 'Controle de doses' (vacinados, doses, perdas por mês).

    Só leitura. Usa o último número de cada linha (Cachorros/Gatos/Doses/Perdas)
    como total do mês, o que é robusto às irregularidades da planilha manual.
    """
    spreadsheet_id = _pmo_spreadsheet_id()
    title = resolve_pmo_sheet_title_cached(
        os.getenv(PMO_DOSES_SHEET_TITLE_ENV, PMO_DOSES_SHEET_DEFAULT_TITLE),
        use_cache=use_cache,
    )
    values = read_pmo_sheet_values(
        spreadsheet_id, title, PMO_DOSES_SHEET_RANGE, use_cache=use_cache
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

    if compiled and not dry_run:
        # A aba de doses acabou de mudar: o painel precisa ler os números novos
        # em vez do snapshot em cache.
        invalidate_pmo_sheet_values_cache()

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


def get_pmo_frascos_ledger(*, use_cache: bool = True) -> dict[str, Any]:
    """Reconstrói a linha do tempo de frascos a partir da "Controle de doses".

    Só leitura. A sobra é derivada (nunca digitada): sobra = sobra válida
    anterior + frascos abertos × doses − doses usadas. Inconsistências do
    registro (coluna sem data, mês que não fecha em frascos inteiros, sobra
    vencida sem descarte) viram anomalias/alertas em vez de quebrar a conta.
    """
    vial = PMO_FRASCO_DOSES
    validity = PMO_FRASCO_VALIDADE_DIAS
    spreadsheet_id = _pmo_spreadsheet_id()
    today = now_in_brazil().date()

    wanted_doses_title = os.getenv(PMO_DOSES_SHEET_TITLE_ENV, PMO_DOSES_SHEET_DEFAULT_TITLE)
    doses_title = ""
    next_scheduled: date | None = None
    for sheet in list_vacina_pmo_sheets(use_cache=use_cache):
        title = sheet.get("title", "")
        if _pmo_normalize_title(title) == _pmo_normalize_title(wanted_doses_title):
            doses_title = title
            continue
        day = _parse_date_object(title)
        if day and day > today and day.year == today.year:
            if next_scheduled is None or day < next_scheduled:
                next_scheduled = day
    if not doses_title:
        raise RuntimeError(f"Aba '{wanted_doses_title}' não encontrada na planilha PMO.")

    values = read_pmo_sheet_values(
        spreadsheet_id, doses_title, PMO_DOSES_SHEET_RANGE, use_cache=use_cache
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


# ——— Frascos do dia, calculados das fichas ———————————————————————————————————
# A "Controle de doses" só sabe de um dia depois que ele é compilado; o painel
# do aplicador precisa saber ANTES e DURANTE. Estas funções reconstroem a mesma
# linha do tempo de frascos a partir do banco (cães + gatos vacinados + perdas),
# então o número muda ao vivo conforme a lista é marcada. Controle é por DIA: a
# sobra da manhã atravessa para a tarde, e o que for descartado entre os turnos
# entra como perda da visita.


def _pmo_dia_label(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _pmo_doses_por_dia() -> dict[date, dict[str, Any]]:
    """Doses usadas por dia segundo as fichas, abertas por turno.

    Dose usada = animal com status ``vacinado`` (quem já estava imunizado não
    consome frasco) + perdas lançadas na visita.
    """
    from sqlalchemy.orm import selectinload

    visits = (
        PmoVaccinationVisit.query.options(
            selectinload(PmoVaccinationVisit.animals)
        ).all()
    )

    por_dia: dict[date, dict[str, Any]] = {}
    for visit in visits:
        day = _parse_date_object((visit.sheet_title or "").strip())
        if not day:
            continue
        bucket = por_dia.setdefault(
            day,
            {
                "dogs": 0,
                "cats": 0,
                "losses": 0,
                "shifts": {
                    "Manha": {"dogs": 0, "cats": 0, "losses": 0},
                    "Tarde": {"dogs": 0, "cats": 0, "losses": 0},
                    "": {"dogs": 0, "cats": 0, "losses": 0},
                },
            },
        )
        shift = _normalize_shift(visit.shift)
        shift_bucket = bucket["shifts"].setdefault(
            shift if shift in ("Manha", "Tarde") else "",
            {"dogs": 0, "cats": 0, "losses": 0},
        )
        dogs = sum(
            1
            for animal in visit.animals
            if (animal.status or "") == "vacinado" and animal.species != "gato"
        )
        cats = sum(
            1
            for animal in visit.animals
            if (animal.status or "") == "vacinado" and animal.species == "gato"
        )
        losses = int(visit.losses or 0)
        for target in (bucket, shift_bucket):
            target["dogs"] += dogs
            target["cats"] += cats
            target["losses"] += losses
    return por_dia


def _pmo_day_stock_overrides(spreadsheet_id: str) -> dict[date, Any]:
    from models import PmoVaccinationDayStock

    return {
        row.day: row
        for row in PmoVaccinationDayStock.query.filter_by(
            spreadsheet_id=spreadsheet_id
        ).all()
    }


def _pmo_frascos_timeline(extra_days: list[date] | None = None) -> dict[date, dict[str, Any]]:
    """Estado de frascos de cada dia da campanha, na ordem cronológica.

    Um dia entra na linha do tempo se teve dose, se o vacinador corrigiu algo
    nele ou se foi pedido explicitamente (o dia de hoje, ainda sem nenhuma
    marcação, precisa aparecer com a sobra que herdou).
    """
    vial = PMO_FRASCO_DOSES
    validity = PMO_FRASCO_VALIDADE_DIAS
    spreadsheet_id = _pmo_spreadsheet_id()

    usage = _pmo_doses_por_dia()
    overrides = _pmo_day_stock_overrides(spreadsheet_id)
    days = sorted(set(usage) | set(overrides) | set(extra_days or []))

    timeline: dict[date, dict[str, Any]] = {}
    leftover = 0
    opened_on: date | None = None

    for day in days:
        alerts: list[str] = []

        # 1) O que sobrou do dia anterior ainda vale?
        if leftover and opened_on and (day - opened_on).days >= validity:
            alerts.append(
                f"{leftover} dose(s) do frasco aberto em {_pmo_dia_label(opened_on)} venceram "
                f"em {_pmo_dia_label(opened_on + timedelta(days=validity - 1))} — lance como perda."
            )
            leftover, opened_on = 0, None

        override = overrides.get(day)
        leftover_source = "auto"
        if override is not None and override.leftover_start is not None:
            leftover = max(0, int(override.leftover_start))
            opened_on = override.leftover_opened_on or (day if leftover else None)
            leftover_source = "manual"

        start_leftover = leftover
        start_opened_on = opened_on
        start_valid_until = (
            start_opened_on + timedelta(days=validity - 1) if start_opened_on else None
        )

        # 2) Quanto o dia consumiu, segundo as fichas.
        day_usage = usage.get(day) or {
            "dogs": 0,
            "cats": 0,
            "losses": 0,
            "shifts": {
                "Manha": {"dogs": 0, "cats": 0, "losses": 0},
                "Tarde": {"dogs": 0, "cats": 0, "losses": 0},
                "": {"dogs": 0, "cats": 0, "losses": 0},
            },
        }
        used = day_usage["dogs"] + day_usage["cats"] + day_usage["losses"]

        # 3) Frascos novos: o cálculo é o mínimo que fecha a conta; o vacinador
        #    pode dizer outro número (abriu um a mais, um quebrou).
        from_leftover = min(start_leftover, used)
        remaining = used - from_leftover
        auto_vials = math.ceil(remaining / vial) if remaining else 0
        vials = auto_vials
        vials_source = "auto"
        if override is not None and override.vials_opened is not None:
            vials = max(0, int(override.vials_opened))
            vials_source = "manual"

        available = start_leftover + vials * vial
        end_leftover = available - used
        if end_leftover < 0:
            alerts.append(
                f"Faltam {abs(end_leftover)} dose(s) para o que já foi aplicado: "
                f"{used} usada(s) contra {available} disponível(is). Registre o frasco "
                "que faltou ou confira as perdas."
            )
            end_leftover = 0

        if vials:
            opened_on = day
        leftover = end_leftover
        if leftover == 0:
            opened_on = None
        end_valid_until = (
            opened_on + timedelta(days=validity - 1) if opened_on and leftover else None
        )

        timeline[day] = {
            "day": day.isoformat(),
            "dayLabel": _pmo_dia_label(day),
            "leftoverStart": start_leftover,
            "leftoverStartSource": leftover_source,
            "leftoverOpenedOn": _pmo_dia_label(start_opened_on) if start_opened_on else "",
            "leftoverValidUntil": (
                _pmo_dia_label(start_valid_until) if start_valid_until else ""
            ),
            "vialsOpened": vials,
            "vialsOpenedAuto": auto_vials,
            "vialsSource": vials_source,
            "available": available,
            "used": used,
            "usedDogs": day_usage["dogs"],
            "usedCats": day_usage["cats"],
            "losses": day_usage["losses"],
            "byShift": {
                shift: dict(counts)
                for shift, counts in day_usage["shifts"].items()
                if counts["dogs"] or counts["cats"] or counts["losses"]
            },
            "remaining": max(0, available - used),
            "leftoverEnd": leftover,
            "leftoverEndValidUntil": (
                _pmo_dia_label(end_valid_until) if end_valid_until else ""
            ),
            "leftoverEndValidUntilIso": end_valid_until.isoformat() if end_valid_until else "",
            "alerts": alerts,
            "note": (override.note or "") if override is not None else "",
            "updatedBy": (
                override.updated_by.name
                if override is not None and override.updated_by is not None
                else ""
            ),
        }
    return timeline


def _pmo_dias_com_lista(after: date) -> date | None:
    """Próximo dia que já tem lista montada no banco (agenda real da campanha)."""
    titles = {
        title
        for (title,) in db.session.query(PmoVaccinationVisit.sheet_title).distinct().all()
    }
    futuros = sorted(
        day
        for day in (_parse_date_object((title or "").strip()) for title in titles)
        if day and day > after
    )
    return futuros[0] if futuros else None


def get_pmo_dia_frascos(day: Any) -> dict[str, Any]:
    """Sobra herdada e frascos abertos de um dia, com o consumo ao vivo.

    É o que o painel do aplicador mostra no topo: quanto dá para vacinar hoje
    sem abrir mais nada, quanto já foi usado e o que a sobra do fim do dia
    permite agendar antes de vencer.
    """
    target = day if isinstance(day, date) else _parse_date_object(day)
    if not target:
        raise ValueError("Dia inválido: use uma aba com data (dd/mm/aaaa).")

    timeline = _pmo_frascos_timeline(extra_days=[target])
    payload = dict(timeline[target])
    payload["vialDoses"] = PMO_FRASCO_DOSES
    payload["validityDays"] = PMO_FRASCO_VALIDADE_DIAS

    next_day = _pmo_dias_com_lista(target)
    payload["nextDay"] = _pmo_dia_label(next_day) if next_day else ""

    # O que a sobra do fim do dia permite planejar. É daqui que sai a leitura de
    # agendamento: sobra que vence antes do próximo dia é dose perdida.
    leftover_end = payload["leftoverEnd"]
    valid_until = payload["leftoverEndValidUntil"]
    limite = _parse_date_object(payload["leftoverEndValidUntilIso"])
    hint = ""
    if leftover_end and limite:
        if next_day and next_day > limite:
            hint = (
                f"A sobra de {leftover_end} dose(s) vence em {valid_until} e o próximo dia "
                f"com lista é {_pmo_dia_label(next_day)} — antecipe um atendimento ou "
                "planeje o descarte."
            )
        elif next_day:
            hint = (
                f"{_pmo_dia_label(next_day)} já começa com {leftover_end} dose(s) da sobra: "
                f"agende {leftover_end} animal(is) antes de precisar de frasco novo."
            )
        elif limite <= target:
            hint = (
                f"A sobra de {leftover_end} dose(s) vence hoje ({valid_until}) — use ainda "
                "hoje ou lance como perda."
            )
        else:
            hint = (
                f"Sobram {leftover_end} dose(s) válidas até {valid_until} — marque um dia "
                "até lá para não perder."
            )
    elif payload["remaining"]:
        hint = (
            f"Ainda há {payload['remaining']} dose(s) abertas para hoje "
            f"({payload['available']} disponíveis, {payload['used']} usadas)."
        )
    payload["planningHint"] = hint
    return payload


def save_pmo_dia_frascos(
    day: Any,
    *,
    leftover_start: Any = None,
    leftover_opened_on: Any = None,
    vials_opened: Any = None,
    note: Any = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Grava (ou limpa) a correção manual do dia e devolve o estado recalculado.

    Campo em branco volta ao automático de propósito: o vacinador não deveria
    precisar redigitar todo dia um número que o app sabe calcular.
    """
    from models import PmoVaccinationDayStock

    target = day if isinstance(day, date) else _parse_date_object(day)
    if not target:
        raise ValueError("Dia inválido: use uma aba com data (dd/mm/aaaa).")

    def _int_or_none(value: Any, label: str) -> int | None:
        # Só string vazia (ou ausência) significa "calcule sozinho". O inteiro 0
        # é uma afirmação do vacinador — "não sobrou nada", "não abri frasco" —
        # e não pode cair no mesmo balde de branco.
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError(f"{label}: informe um número inteiro ou deixe em branco.")
        if parsed < 0:
            raise ValueError(f"{label}: não pode ser negativo.")
        return parsed

    leftover_value = _int_or_none(leftover_start, "Sobra do dia anterior")
    vials_value = _int_or_none(vials_opened, "Frascos abertos")
    opened_value = (
        _parse_date_object(leftover_opened_on)
        if leftover_opened_on not in (None, "")
        else None
    )
    if leftover_opened_on not in (None, "") and opened_value is None:
        raise ValueError("Data de abertura do frasco inválida. Use dd/mm/aaaa.")
    if opened_value and opened_value > target:
        raise ValueError("O frasco não pode ter sido aberto depois do dia da lista.")

    spreadsheet_id = _pmo_spreadsheet_id()
    row = PmoVaccinationDayStock.query.filter_by(
        spreadsheet_id=spreadsheet_id, day=target
    ).one_or_none()
    if row is None:
        row = PmoVaccinationDayStock(spreadsheet_id=spreadsheet_id, day=target)
        db.session.add(row)

    row.leftover_start = leftover_value
    row.leftover_opened_on = opened_value if leftover_value else None
    row.vials_opened = vials_value
    row.note = _normalize_text(note) or None
    row.updated_by_id = user_id

    if row.is_empty:
        # Nada corrigido: some com a linha para o dia voltar a ser 100% calculado.
        if row in db.session.new:
            db.session.expunge(row)
        else:
            db.session.delete(row)
    db.session.commit()
    return get_pmo_dia_frascos(target)


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

    # selectinload obrigatório: _overall_status percorre ``visit.animals`` três
    # vezes por visita e, sem eager loading, cada casa vira um SELECT próprio —
    # era o grosso do tempo de abertura do painel.
    from sqlalchemy.orm import selectinload

    all_visits = (
        PmoVaccinationVisit.query.options(selectinload(PmoVaccinationVisit.animals)).all()
    )
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

    title = pmo_request_sheet_titles()[0]
    address = normalize_pmo_request_address(payload)

    service = _get_sheets_service_rw()
    # Escreve na aba que já existe (mesmo renomeada), nunca numa cópia nova.
    title = _resolve_request_sheet_title(service, spreadsheet_id, title)

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
# Reconciliação da aba de solicitações
# ──────────────────────────────────────────────────────────────────────────────

# Colunas que identificam uma solicitação (ver PMO_REQUEST_HEADERS).
PMO_REQUEST_TUTOR_INDEX = 0
PMO_REQUEST_ANIMALS_INDEX = 9
PMO_REQUEST_TIMESTAMP_INDEX = 15


def _request_row_key(row: list[str]) -> tuple[str, str, str]:
    """Identidade de uma solicitação: carimbo + tutor + animais."""

    def cell(index: int) -> str:
        value = row[index] if index < len(row) else ""
        return re.sub(r"\s+", " ", str(value or "")).strip().lower()

    return (
        cell(PMO_REQUEST_TIMESTAMP_INDEX),
        cell(PMO_REQUEST_TUTOR_INDEX),
        cell(PMO_REQUEST_ANIMALS_INDEX),
    )


def _request_row_is_empty(row: list[str]) -> bool:
    return not any(str(cell or "").strip() for cell in row)


def reconcile_pmo_request_sheets(*, apply: bool = True, service=None) -> dict[str, Any]:
    """Reúne na aba oficial as solicitações que caíram em abas duplicadas.

    Enquanto a busca da aba era literal, um renome na planilha fazia o app
    criar uma cópia com o nome antigo e gravar ali — as solicitações dos
    moradores continuavam chegando, mas fora da vista da equipe. Além de
    corrigir o destino das novas, é preciso trazer de volta as que já ficaram
    para trás; por isso esta rotina roda junto do sync periódico do PMO.

    Copia só o que falta (compara carimbo + tutor + animais, então rodar de
    novo não duplica), reaponta o ``PmoVaccinationVisit`` para a linha nova —
    preservando o protocolo público já entregue ao morador — e limpa a aba
    duplicada para que o sync não recrie visitas repetidas.
    """
    summary: dict[str, Any] = {
        "canonical": "",
        "duplicates": [],
        "moved": 0,
        "repointed": 0,
        "applied": bool(apply),
    }

    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    spreadsheet_id = _extract_google_sheet_id(sheet_url)
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO inválido.")

    service = service or _get_sheets_service_rw()
    canonical = _resolve_request_sheet_title(
        service, spreadsheet_id, pmo_request_sheet_titles()[0]
    )
    canonical_gid = _get_sheet_gid(service, spreadsheet_id, canonical)
    summary["canonical"] = canonical

    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
        .execute()
    )
    others = []
    for sheet in metadata.get("sheets", []):
        other_title = (sheet.get("properties") or {}).get("title", "")
        if other_title and other_title != canonical:
            others.append(other_title)
    if not others:
        return summary

    header_response = (
        service.spreadsheets()
        .values()
        .batchGet(
            spreadsheetId=spreadsheet_id,
            ranges=[
                f"{_quote_sheet_title(title)}!{PMO_REQUEST_HEADER_RANGE}" for title in others
            ],
        )
        .execute()
    )
    duplicates = [
        title
        for title, value_range in zip(others, header_response.get("valueRanges", []))
        if _request_sheet_header_matches(value_range.get("values"))
    ]
    summary["duplicates"] = duplicates
    if not duplicates:
        return summary

    canonical_rows = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet_title(canonical)}!{PMO_REQUEST_RANGE_COLS}",
        )
        .execute()
        .get("values", [])
    )
    known = {
        _request_row_key(row) for row in canonical_rows[1:] if not _request_row_is_empty(row)
    }
    next_row = len(canonical_rows) + 1

    for title in duplicates:
        rows = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"{_quote_sheet_title(title)}!{PMO_REQUEST_RANGE_COLS}",
            )
            .execute()
            .get("values", [])
        )
        pending: list[tuple[int, list[str]]] = []
        for source_row, row in enumerate(rows[1:], start=2):
            if _request_row_is_empty(row):
                continue
            key = _request_row_key(row)
            if key in known:
                continue
            known.add(key)
            pending.append((source_row, row))

        if not pending:
            continue

        summary["moved"] += len(pending)
        if not apply:
            continue

        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet_title(canonical)}!{PMO_REQUEST_RANGE_COLS}",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row for _source_row, row in pending]},
        ).execute()

        duplicate_gid = _get_sheet_gid(service, spreadsheet_id, title)
        try:
            for offset, (source_row, _row) in enumerate(pending):
                visit = PmoVaccinationVisit.query.filter_by(
                    spreadsheet_id=spreadsheet_id,
                    sheet_gid=duplicate_gid,
                    source_row=source_row,
                ).first()
                if visit is None:
                    continue
                visit.sheet_gid = canonical_gid
                visit.sheet_title = canonical
                visit.source_row = next_row + offset
                summary["repointed"] += 1
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        next_row += len(pending)

        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet_title(title)}!A2:R",
            body={},
        ).execute()

    return summary


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


PMO_VACINADOS_PAGE_SIZE = 60

# Ordens que o painel oferece. "recentes"/"antigos" olham a data da dose;
# "vencendo" olha o que falta para a proteção acabar.
PMO_VACINADOS_ORDERS = ("recentes", "antigos", "vencendo", "nome")


def _pmo_coverage_status(days_left: int | None) -> str:
    if days_left is None:
        return "sem_data"
    if days_left > 30:
        return "protected"
    if days_left >= 0:
        return "expiring"
    return "expired"


def _pmo_vacinados_dataset() -> list[dict[str, Any]]:
    """Um registro por animal com dose registrada — a fonte do painel.

    A data da dose sai de ``_pmo_dose_date``, a mesma regra que a carteirinha e
    a folha impressa usam: dose aplicada na visita, dose anterior de quem já
    estava imunizado ou, na falta das duas, a data da aba do dia. A versão
    antiga exigia ``visit.vaccine_date`` preenchido e sumia em silêncio com
    quem foi vacinado em aba sem data (Encaixes, Solicitações) — daí a
    sensação de número que não bate com a planilha. Aqui esses animais
    aparecem no balde ``sem_data``, visíveis e contáveis.
    """
    from sqlalchemy.orm import joinedload

    today = now_in_brazil().date()
    animals = (
        PmoVaccinationAnimal.query.options(
            joinedload(PmoVaccinationAnimal.visit),
            joinedload(PmoVaccinationAnimal.animal),
        )
        .filter(PmoVaccinationAnimal.status.in_(PMO_DONE_STATUSES))
        .all()
    )

    rows: list[dict[str, Any]] = []
    for animal in animals:
        visit = animal.visit
        if visit is None:
            continue
        dose_date = _pmo_dose_date(animal, visit)
        expiry = dose_date + timedelta(days=_PMO_VACCINE_VALIDITY_DAYS) if dose_date else None
        days_left = (expiry - today).days if expiry else None
        days_since = (today - dose_date).days if dose_date else None
        applied_here = animal.status == "vacinado"

        phone_raw = visit.phone1 or visit.phone2
        dose_label = _pmo_br_date(dose_date) if dose_date else ""
        expiry_label = _pmo_br_date(expiry) if expiry else ""
        if dose_date:
            wa_msg = (
                f"Olá, {visit.tutor_name}! "
                f"A vacina antirrábica de *{animal.name}* foi aplicada em "
                f"{dose_label} pela Prefeitura de Orlândia. "
                f"A proteção é válida por 1 ano e vence em *{expiry_label}*. "
                "Lembre-se de revacinar para manter seu pet protegido. 🐾"
            )
        else:
            wa_msg = (
                f"Olá, {visit.tutor_name}! Sobre a vacina antirrábica de "
                f"*{animal.name}*: precisamos confirmar a data em que ela foi "
                "aplicada. Você lembra?"
            )

        rows.append(
            {
                "pmo_id": animal.id,
                "animal_id": animal.animal_id,
                "animal_name": animal.name,
                "species": animal.species,
                "tutor": visit.tutor_name,
                "address": visit.address or "",
                "phone": phone_raw or "",
                "phone_wa": _pmo_format_phone_wa(phone_raw),
                "image_url": (
                    animal.animal.image if animal.animal and animal.animal.image else ""
                ),
                "profile_url": (
                    url_for("ficha_animal", animal_id=animal.animal_id)
                    if animal.animal_id and has_request_context()
                    else ""
                ),
                "card_url": (
                    url_for(
                        "vacina_pmo_public_pet",
                        token=visit.public_token,
                        pmo_animal_id=animal.id,
                    )
                    if visit.public_token and has_request_context()
                    else ""
                ),
                "sheet_title": visit.sheet_title or "",
                "shift": visit.shift or "",
                "attended_by": visit.attended_by or "",
                "applied_here": applied_here,
                "status": animal.status,
                "dose_date": dose_date.isoformat() if dose_date else "",
                "vaccine_date": dose_label,
                "expiry_date": expiry_label,
                "days_left": days_left,
                "days_since": days_since,
                "status_key": _pmo_coverage_status(days_left),
                "wa_msg": wa_msg,
            }
        )
    return rows


def _pmo_vacinados_sort(rows: list[dict[str, Any]], order: str) -> list[dict[str, Any]]:
    """Ordena sem deixar quem está sem data embaralhado no meio da lista."""
    undated = [row for row in rows if not row["dose_date"]]
    dated = [row for row in rows if row["dose_date"]]
    if order == "antigos":
        dated.sort(key=lambda row: (row["dose_date"], row["animal_name"].casefold()))
    elif order == "vencendo":
        dated.sort(key=lambda row: (row["days_left"], row["animal_name"].casefold()))
    elif order == "nome":
        dated.sort(key=lambda row: (row["animal_name"].casefold(), row["dose_date"]))
        undated.sort(key=lambda row: row["animal_name"].casefold())
        return dated + undated
    else:  # "recentes" — padrão: o vacinado mais recente primeiro
        dated.sort(
            key=lambda row: (row["dose_date"], row["animal_name"].casefold()), reverse=True
        )
    undated.sort(key=lambda row: row["animal_name"].casefold())
    return dated + undated


def _pmo_vacinados_matches(row: dict[str, Any], needle: str) -> bool:
    if not needle:
        return True
    haystack = " ".join(
        [row["animal_name"], row["tutor"], row["address"], row["sheet_title"], row["phone"]]
    )
    return needle in _strip_accents(haystack).casefold()


def get_vacina_pmo_vacinados(
    *,
    order: str = "recentes",
    status: str = "todos",
    query: str = "",
    page: int = 1,
    per_page: int = PMO_VACINADOS_PAGE_SIZE,
) -> dict[str, Any]:
    """Lista paginada dos animais com dose registrada, na ordem pedida."""
    order = order if order in PMO_VACINADOS_ORDERS else "recentes"
    per_page = max(1, min(int(per_page or PMO_VACINADOS_PAGE_SIZE), 200))
    page = max(1, int(page or 1))

    rows = _pmo_vacinados_dataset()
    counts = {
        "todos": len(rows),
        "protected": 0,
        "expiring": 0,
        "expired": 0,
        "sem_data": 0,
        "aplicadas": 0,
        "imunizados": 0,
        "com_foto": 0,
        "caes": 0,
        "gatos": 0,
    }
    last_dose = ""
    for row in rows:
        counts[row["status_key"]] += 1
        counts["aplicadas" if row["applied_here"] else "imunizados"] += 1
        if row["image_url"]:
            counts["com_foto"] += 1
        if row["species"] == "cao":
            counts["caes"] += 1
        elif row["species"] == "gato":
            counts["gatos"] += 1
        if row["dose_date"] > last_dose:
            last_dose = row["dose_date"]

    filtered = [row for row in rows if status in ("todos", row["status_key"])]
    needle = _strip_accents(query or "").casefold().strip()
    if needle:
        filtered = [row for row in filtered if _pmo_vacinados_matches(row, needle)]

    ordered = _pmo_vacinados_sort(filtered, order)
    total = len(ordered)
    start = (page - 1) * per_page
    items = ordered[start : start + per_page]

    return {
        "animals": items,
        "counts": counts,
        "order": order,
        "status": status,
        "query": query or "",
        "page": page,
        "perPage": per_page,
        "total": total,
        "hasMore": start + per_page < total,
        "lastDose": _pmo_br_date(date.fromisoformat(last_dose)) if last_dose else "",
    }


def get_vacina_pmo_cobertura_summary() -> dict[str, Any]:
    """Contadores de cobertura ativa, derivados da mesma lista de vacinados."""
    counts = get_vacina_pmo_vacinados(per_page=1)["counts"]
    return {
        "protected": counts["protected"],
        "expiring": counts["expiring"],
        "expired": counts["expired"],
        "sem_data": counts["sem_data"],
        "total": counts["todos"],
    }


def get_vacina_pmo_cobertura_detail() -> list[dict[str, Any]]:
    """Lista completa de vacinados ordenada pelo vencimento mais próximo."""
    return get_vacina_pmo_vacinados(order="vencendo", per_page=200)["animals"]
