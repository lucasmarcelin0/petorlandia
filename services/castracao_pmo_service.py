"""Google Sheets helpers for PMO castration requests."""

from __future__ import annotations

import os
import re
import secrets
from datetime import date
from typing import Any

from extensions import db
from models import Animal, PmoCastrationAnimal, PmoCastrationRequest
from services.sfa_service import _extract_google_sheet_id
from services.vacina_pmo_service import (
    _get_sheet_gid,
    _get_sheets_service_rw,
    _normalize_text,
    _quote_sheet_title,
    normalize_pmo_request_address,
    resolve_request_sheet_title,
)
from time_utils import utcnow


PMO_CASTRATION_SHEET_URL_ENV = "PMO_CASTRATION_SHEET_URL"
PMO_CASTRATION_DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1V1uy_x_ZOdZ3KVa3X-mhh2FOONBCYrUmicwPGKIwqJg/edit?gid=0#gid=0"
)
PMO_CASTRATION_REQUEST_SHEET_TITLE_ENV = "PMO_CASTRATION_REQUEST_SHEET_TITLE"
PMO_CASTRATION_REQUEST_SHEET_DEFAULT_TITLE = "Solicitacoes Castracao"
# Nomes que esta aba já teve. Serve para reencontrá-la depois de um renome e
# para o histórico do morador não sumir junto.
PMO_CASTRATION_REQUEST_SHEET_LEGACY_TITLES: tuple[str, ...] = ()
PMO_CASTRATION_REQUEST_RANGE_COLS = "A:U"
PMO_CASTRATION_REQUEST_HEADER_RANGE = "A1:U1"
PMO_CASTRATION_REQUEST_HEADERS = [
    "Nome completo do tutor",
    "CPF",
    "E-mail",
    "Endereco",
    "Numero da casa",
    "Complemento",
    "Bairro",
    "Telefone",
    "Telefone 2 ou recado",
    "Quantidade de cachorros",
    "Quantidade de gatos",
    "Nome do(s) animal(is)",
    "Detalhes dos animais",
    "Preferencia de contato",
    "Situacao de femeas",
    "Observacoes de saude",
    "Observacao geral",
    "Carimbo de data/hora",
    "Origem",
    "ID Usuario PetOrlandia",
    "Status",
]


def _sheet_url() -> str:
    return os.getenv(PMO_CASTRATION_SHEET_URL_ENV) or PMO_CASTRATION_DEFAULT_SHEET_URL


def _public_token() -> str:
    return secrets.token_urlsafe(32)


def _ensure_public_token(request_obj: PmoCastrationRequest) -> None:
    if request_obj.public_token:
        return
    while True:
        token = _public_token()
        if not PmoCastrationRequest.query.filter_by(public_token=token).first():
            request_obj.public_token = token
            return


def pmo_castration_request_sheet_titles() -> list[str]:
    """Títulos aceitos para a aba de solicitações de castração."""
    configurado = _normalize_text(os.getenv(PMO_CASTRATION_REQUEST_SHEET_TITLE_ENV, ""))
    titulos = [configurado or PMO_CASTRATION_REQUEST_SHEET_DEFAULT_TITLE]
    for legado in (
        PMO_CASTRATION_REQUEST_SHEET_DEFAULT_TITLE,
        *PMO_CASTRATION_REQUEST_SHEET_LEGACY_TITLES,
    ):
        if legado and legado not in titulos:
            titulos.append(legado)
    return titulos


def _resolve_castration_request_sheet_title(
    service, spreadsheet_id: str, title: str, *, create: bool = True
) -> str:
    """Aba de solicitações da CASTRAÇÃO, encontrada mesmo se renomeada.

    A busca era literal e criava uma cópia vazia quando o nome não batia — a
    mesma falha que escondeu as solicitações de vacina da equipe. Aqui o risco
    é maior: a castração não tem painel nem sincronização, então essa aba é a
    única janela para as inscrições. O cabeçalho de 21 colunas distingue esta
    aba da de vacina, que tem nome parecido e colunas diferentes.
    """
    return resolve_request_sheet_title(
        service,
        spreadsheet_id,
        title,
        aliases=pmo_castration_request_sheet_titles(),
        headers=PMO_CASTRATION_REQUEST_HEADERS,
        header_range=PMO_CASTRATION_REQUEST_HEADER_RANGE,
        create=create,
    )


def _species_key(animal: Animal) -> str:
    species_name = (animal.species.name if animal.species else "").lower()
    return "gato" if "gat" in species_name else "cao"


def _age_label(animal: Animal) -> str:
    if not animal.date_of_birth:
        return ""
    today = date.today()
    years = today.year - animal.date_of_birth.year
    months = today.month - animal.date_of_birth.month
    if today.day < animal.date_of_birth.day:
        months -= 1
    if months < 0:
        years -= 1
        months += 12
    if years > 0:
        return f"{years} ano(s)" + (f" e {months} mes(es)" if months else "")
    return f"{max(months, 0)} mes(es)"


def build_castration_animal_payloads(animals: list[Animal]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for animal in animals:
        payloads.append(
            {
                "animal_id": animal.id,
                "name": animal.name or "Sem nome",
                "species": _species_key(animal),
                "sex": animal.sex or "",
                "age_label": _age_label(animal),
                "weight_kg": animal.peso,
                "already_neutered": animal.neutered,
            }
        )
    return payloads


def format_castration_animal_details(items: list[dict[str, Any]]) -> str:
    details: list[str] = []
    for item in items:
        parts = [
            item.get("name") or "Sem nome",
            "cao" if item.get("species") == "cao" else "gato",
        ]
        if item.get("sex"):
            parts.append(str(item["sex"]))
        if item.get("age_label"):
            parts.append(str(item["age_label"]))
        if item.get("weight_kg") is not None:
            parts.append(f"{item['weight_kg']} kg")
        if item.get("already_neutered") is not None:
            parts.append("castrado" if item.get("already_neutered") else "nao castrado")
        details.append(" - ".join(parts))
    return "; ".join(details)


def submit_castracao_pmo_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Append a PMO castration request to Sheets and keep a local history."""
    spreadsheet_id = _extract_google_sheet_id(_sheet_url())
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO invalido.")

    title = pmo_castration_request_sheet_titles()[0]
    address = normalize_pmo_request_address(payload)
    animal_items = list(payload.get("animals") or [])
    dogs = sum(1 for item in animal_items if item.get("species") == "cao")
    cats = sum(1 for item in animal_items if item.get("species") == "gato")
    animal_names = ", ".join(_normalize_text(item.get("name")) for item in animal_items if _normalize_text(item.get("name")))
    animal_details = format_castration_animal_details(animal_items)

    service = _get_sheets_service_rw()
    # Grava na aba que já existe (mesmo renomeada), nunca numa cópia nova.
    title = _resolve_castration_request_sheet_title(service, spreadsheet_id, title)

    submitted_at = utcnow()
    timestamp = submitted_at.astimezone().strftime("%d/%m/%Y %H:%M:%S")
    row = [
        _normalize_text(payload.get("tutor")),
        _normalize_text(payload.get("cpf")),
        _normalize_text(payload.get("email")),
        address["street"],
        address["number"],
        address["complement"],
        address["neighborhood"],
        _normalize_text(payload.get("phone")),
        _normalize_text(payload.get("phone2")),
        str(dogs),
        str(cats),
        animal_names,
        animal_details,
        _normalize_text(payload.get("preferred_contact")),
        _normalize_text(payload.get("female_status")),
        _normalize_text(payload.get("health_notes")),
        _normalize_text(payload.get("note")),
        timestamp,
        "PetOrlandia",
        str(payload.get("user_id") or ""),
        "Solicitado",
    ]

    response = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet_title(title)}!{PMO_CASTRATION_REQUEST_RANGE_COLS}",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        )
        .execute()
    )

    updated_range = response.get("updates", {}).get("updatedRange", "")
    source_row = 0
    match = re.search(r"!A(\d+)", updated_range)
    if match:
        source_row = int(match.group(1))
    sheet_gid = _get_sheet_gid(service, spreadsheet_id, title)

    public_token: str | None = None
    if source_row and sheet_gid is not None:
        try:
            request_obj = PmoCastrationRequest.query.filter_by(
                spreadsheet_id=spreadsheet_id,
                sheet_gid=sheet_gid,
                source_row=source_row,
            ).first()
            if request_obj is None:
                request_obj = PmoCastrationRequest(
                    spreadsheet_id=spreadsheet_id,
                    sheet_gid=sheet_gid,
                    sheet_title=title,
                    source_row=source_row,
                    tutor_name=_normalize_text(payload.get("tutor")),
                    submitted_at=submitted_at,
                    synced_at=submitted_at,
                    updated_at=submitted_at,
                )
                db.session.add(request_obj)

            request_obj.cpf = _normalize_text(payload.get("cpf"))
            request_obj.email = _normalize_text(payload.get("email"))
            request_obj.address = address["full"]
            request_obj.phone1 = _normalize_text(payload.get("phone"))
            request_obj.phone2 = _normalize_text(payload.get("phone2"))
            request_obj.dogs = dogs
            request_obj.cats = cats
            request_obj.preferred_contact = _normalize_text(payload.get("preferred_contact"))
            request_obj.female_status = _normalize_text(payload.get("female_status"))
            request_obj.health_notes = _normalize_text(payload.get("health_notes"))
            request_obj.note = _normalize_text(payload.get("note"))
            request_obj.status = "solicitado"
            request_obj.tutor_user_id = int(payload["user_id"]) if payload.get("user_id") else None
            request_obj.synced_at = submitted_at
            request_obj.updated_at = submitted_at
            _ensure_public_token(request_obj)

            request_obj.animals.clear()
            for index, item in enumerate(animal_items, start=1):
                request_obj.animals.append(
                    PmoCastrationAnimal(
                        position=index,
                        animal_id=item.get("animal_id"),
                        name=(_normalize_text(item.get("name")) or "Sem nome")[:120],
                        species=item.get("species") or "cao",
                        sex=_normalize_text(item.get("sex")) or None,
                        age_label=_normalize_text(item.get("age_label")) or None,
                        weight_kg=item.get("weight_kg"),
                        already_neutered=item.get("already_neutered"),
                        status="solicitado",
                    )
                )
            db.session.commit()
            public_token = request_obj.public_token
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
