import argparse
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from googleapiclient.errors import HttpError

from app import app
from models import PmoVaccinationVisit
from services.sfa_service import _extract_google_sheet_id
from services.vacina_pmo_service import (
    DEFAULT_SHEET_URL,
    PMO_STATUS_CLEAR_COLOR,
    PMO_STATUS_COLORS,
    _get_sheets_service_rw,
    _parse_date_object,
    _row_column_offset,
    infer_visit_status,
    list_vacina_pmo_sheets,
    persist_vacina_pmo_rows,
    pmo_request_sheet_titles,
    sync_vacina_pmo_sheet,
)

from scripts.audit_pmo_sheet_status_colors import _fetch_sheet_rows, _row_values


MASTER_SHEET_TITLE = "Vacinação 2026"
TIMESTAMP_COLUMN_INDEX = 0
STATUS_LINK_COLUMN_INDEX = 12
LEGEND_START_COLUMN_INDEX = 13
LEGEND_END_COLUMN_INDEX = 16
PMO_ACTIVE_FLOW_COLOR = {"red": 0.788, "green": 0.855, "blue": 0.973}
DATED_SHEET_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$")
AUXILIARY_TITLES = {
    "controle de doses",
    "padrão",
    "padrao",
    "copia",
    "interesse vacina",
    "teste do bot",
}
TRACKED_NON_DATE_TITLES = {
    "agendadas",
    "encaixes",
    "inscrição a agendar",
    "inscricao a agendar",
}
STATUS_LABELS = {
    "vacinado": "Vacinado",
    "parcial": "Parcial",
    "parcial_encerrado": "Parcial encerrado",
    "remarcar": "Remarcar",
    "recusou": "Cancelado/recusou",
    "ausente": "Ausente",
    "pendente": "Pendente",
    "agendado": "Agendado",
    "fluxo_ativo": "Fluxo ativo",
    "perdeu_contato": "Perdeu contato",
    "reagendar": "Reagendar",
}
# Laranja para "parcial encerrado": alguns animais foram vacinados mas o tutor
# recusou o retorno via Encaixes — caso fechado sem possibilidade de completar.
PMO_PARCIAL_ENCERRADO_COLOR = {"red": 0.988, "green": 0.800, "blue": 0.549}
STATUS_COLORS = {
    "vacinado": PMO_STATUS_COLORS["vacinado"],
    "parcial": PMO_STATUS_COLORS["parcial"],
    "parcial_encerrado": PMO_PARCIAL_ENCERRADO_COLOR,
    "remarcar": PMO_STATUS_COLORS["parcial"],
    "recusou": PMO_STATUS_COLORS["recusou"],
    "ausente": PMO_STATUS_COLORS["ausente"],
    "pendente": PMO_STATUS_CLEAR_COLOR,
    "sem_registro": PMO_STATUS_CLEAR_COLOR,
    "agendado": PMO_ACTIVE_FLOW_COLOR,
    "fluxo_ativo": PMO_ACTIVE_FLOW_COLOR,
    "perdeu_contato": PMO_STATUS_COLORS["parcial"],
    "reagendar": PMO_STATUS_CLEAR_COLOR,
}
LEGEND_ROWS = [
    ("Cor", "Onde aparece", "Significado"),
    ("Verde", "Coluna M", "Vacinado confirmado."),
    ("Vermelho", "Coluna M / Encaixes", "Cancelado/recusou. Não foi e não será feito."),
    ("Laranja", "Coluna M", "Parcial encerrado: alguns animais vacinados, tutor recusou retorno via Encaixes."),
    ("Amarelo", "Coluna M / Encaixes", "Atenção: parcial, remarcar ou perdeu contato com o tutor."),
    ("Azul claro", "Coluna M", "Já está no fluxo normal: agendado ou em Inscrição a agendar."),
    ("Branco", "Coluna M", "Ainda precisa de acompanhamento: pendente, reagendar ou sem registro."),
    ("Azul", "Somente Encaixes", "Voltou para reagendamento. Na coluna M deve aparecer o destino real ou Reagendar."),
]
LEGEND_SWATCH_COLORS = [
    None,
    PMO_STATUS_COLORS["vacinado"],
    PMO_STATUS_COLORS["recusou"],
    PMO_PARCIAL_ENCERRADO_COLOR,
    PMO_STATUS_COLORS["parcial"],
    PMO_ACTIVE_FLOW_COLOR,
    PMO_STATUS_CLEAR_COLOR,
    PMO_ACTIVE_FLOW_COLOR,
]


def _strip_accents(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(char)
    )


def _normalize_text_key(value: str) -> str:
    text = _strip_accents(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tracked_non_date_titles() -> set[str]:
    """Abas de fila/agendamento que o sync periódico acompanha, normalizadas.

    A aba de solicitações entra por ``pmo_request_sheet_titles`` (nome em uso
    hoje + nomes antigos) em vez de por um literal: quando ela foi renomeada na
    planilha, a lista fixa deixou de casar e o sync parou de ler as
    solicitações — elas não chegavam ao banco nem ao compilado de status.
    """
    titles = set(TRACKED_NON_DATE_TITLES)
    titles.update(_normalize_text_key(title) for title in pmo_request_sheet_titles())
    return titles


def _digits(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


def _phone_digit_keys(*values: str | None) -> set[str]:
    """Sufixos que identificam um telefone, em todas as grafias da planilha.

    Além dos dígitos da célula inteira, cada sequência longa de dígitos vira
    chave por conta própria: a equipe às vezes digita os dois números na mesma
    célula ("16992510438 / 16991443152"), e sem isso a colagem dos dois viraria
    uma chave que não bate com nada.
    """
    keys: set[str] = set()
    candidates: list[str] = []
    for value in values:
        text = str(value or "")
        candidates.append(_digits(text))
        candidates.extend(run for run in re.findall(r"\d{8,}", text))
    for digits in candidates:
        if len(digits) >= 8:
            keys.add(digits[-8:])
        if len(digits) >= 10:
            keys.add(digits[-10:])
        if len(digits) >= 11:
            keys.add(digits[-11:])
    return keys


def _phone_keys(visit: PmoVaccinationVisit) -> set[str]:
    return _phone_digit_keys(visit.phone1, visit.phone2)


def _strong_phone_keys(keys: set[str]) -> set[str]:
    """Só as chaves com DDD (10+ dígitos).

    A chave de 8 dígitos existe para casar um fixo digitado sem DDD, mas duas
    pessoas diferentes podem terminar nos mesmos 8 dígitos. Quando o telefone é
    a ÚNICA prova de identidade (conferência de linha da planilha), exigimos a
    versão com DDD.
    """
    return {key for key in keys if len(key) >= 10}


def _name_key(visit: PmoVaccinationVisit) -> str:
    return _normalize_text_key(visit.tutor_name or "")


def _name_tokens(value: str) -> set[str]:
    return {
        token
        for token in _normalize_text_key(value).split()
        if len(token) >= 3
    }


def _name_token_list(value: str) -> list[str]:
    return [token for token in _normalize_text_key(value).split() if token]


def _tokens_match(left: str, right: str) -> bool:
    """Dois pedaços de nome que podem ser a mesma palavra.

    Igualdade, ou uma inicial abreviando a outra ("Raquel F." / "Raquel
    Feliciano"). A planilha abrevia sobrenome o tempo todo.
    """
    if left == right:
        return True
    if len(left) == 1 and right.startswith(left):
        return True
    return len(right) == 1 and left.startswith(right)


def _is_ordered_subsequence(short: list[str], long: list[str]) -> bool:
    iterator = iter(long)
    for token in short:
        for candidate in iterator:
            if _tokens_match(token, candidate):
                break
        else:
            return False
    return True


def _name_texts_compatible(left: str, right: str) -> bool:
    """Duas grafias que podem ser a MESMA pessoa.

    A comparação é por tokens. A versão anterior aceitava substring crua
    (``"ana lima" in "joana lima"`` é verdadeiro), e bastava isso mais uma
    coincidência de telefone para o status de um tutor ser compilado no nome de
    outro. Agora:

    1. grafias idênticas;
    2. a curta é subsequência ordenada da longa (só faltam nomes do meio);
    3. só o primeiro nome de um lado, e ele ABRE o nome completo do outro
       ("Maria" / "Maria Aparecida", nunca "Maria" / "Ana Maria Costa");
    4. 75% ou mais dos tokens (3+ letras) em comum, com pelo menos dois de cada
       lado.
    """
    left_key = _normalize_text_key(left)
    right_key = _normalize_text_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True

    left_list = _name_token_list(left)
    right_list = _name_token_list(right)
    short, long = sorted((left_list, right_list), key=len)
    if not short:
        return False
    if len(short) == 1:
        return len(short[0]) >= 3 and short[0] == long[0]
    if _is_ordered_subsequence(short, long):
        return True

    left_tokens = _name_tokens(left)
    right_tokens = _name_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    smaller = min(len(left_tokens), len(right_tokens))
    return smaller >= 2 and (overlap / smaller) >= 0.75


def _names_compatible(left: PmoVaccinationVisit, right: PmoVaccinationVisit) -> bool:
    return _name_texts_compatible(left.tutor_name or "", right.tutor_name or "")


def _animal_names(visit: PmoVaccinationVisit) -> str:
    names = [animal.name for animal in visit.animals if animal.name]
    return ", ".join(names) if names else "sem pets na linha"


def _sheet_sort_key(visit: PmoVaccinationVisit) -> tuple[int, date, str, int]:
    parsed_date = _parse_date_object((visit.sheet_title or "").strip())
    if parsed_date:
        return (0, parsed_date, visit.sheet_title or "", visit.source_row or 0)
    return (1, date.max, visit.sheet_title or "", visit.source_row or 0)


def _should_sync_sheet(title: str, *, request_titles: set[str] | None = None) -> bool:
    """Decide se a aba entra no sync periódico.

    ``request_titles`` é a aba de solicitações que vale AGORA, resolvida na
    planilha (normalizada). Quando informada, ela substitui a lista de
    apelidos: assim uma aba renomeada para um nome desconhecido — que o app
    reconhece pelo cabeçalho e usa para gravar — também é lida, e as cópias
    duplicadas que ficaram para trás não são, evitando visita repetida para a
    mesma solicitação. Sem ela (uso avulso do script) vale a lista de apelidos.
    """
    normalized = _normalize_text_key(title)
    if normalized in AUXILIARY_TITLES:
        return False
    tracked = (
        set(TRACKED_NON_DATE_TITLES) | request_titles
        if request_titles is not None
        else _tracked_non_date_titles()
    )
    return title == MASTER_SHEET_TITLE or DATED_SHEET_RE.match(title or "") or normalized in tracked


def _is_encaixes(visit: PmoVaccinationVisit) -> bool:
    return _normalize_text_key(visit.sheet_title or "") == "encaixes"


def _is_inscricao_a_agendar(visit: PmoVaccinationVisit) -> bool:
    return _normalize_text_key(visit.sheet_title or "") == "inscricao a agendar"


def _retry_execute(request, *, attempts: int = 4):
    last_error = None
    for attempt in range(attempts):
        try:
            return request.execute()
        except HttpError as exc:
            last_error = exc
            if exc.resp.status not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise last_error


def _resolve_sheet_id_by_title(service, spreadsheet_id: str) -> dict[str, int]:
    metadata = _retry_execute(
        service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
    )
    return {
        sheet["properties"].get("title", ""): int(sheet["properties"].get("sheetId"))
        for sheet in metadata.get("sheets", [])
        if sheet.get("properties", {}).get("title")
    }


def _sync_relevant_sheets(*, request_titles: set[str] | None = None) -> tuple[int, int]:
    total_sheets = 0
    total_rows = 0
    for sheet in list_vacina_pmo_sheets():
        title = sheet.get("title") or ""
        if not _should_sync_sheet(title, request_titles=request_titles):
            continue
        result = sync_vacina_pmo_sheet(sheet_gid=sheet.get("gid") or "", sheet_title=title)
        saved = persist_vacina_pmo_rows(
            result.rows,
            spreadsheet_id=result.spreadsheet_id,
            sheet_gid=result.sheet_gid,
            sheet_title=result.sheet_title,
            prune_orphans=True,
        )
        total_sheets += 1
        total_rows += len(saved)
    return total_sheets, total_rows


def _build_visit_index(visits: list[PmoVaccinationVisit]):
    by_phone = defaultdict(list)
    by_name = defaultdict(list)
    by_user = defaultdict(list)
    for visit in visits:
        if visit.sheet_title == MASTER_SHEET_TITLE:
            continue
        for key in _phone_keys(visit):
            by_phone[key].append(visit)
        name_key = _name_key(visit)
        if name_key:
            by_name[name_key].append(visit)
        if visit.tutor_user_id:
            by_user[visit.tutor_user_id].append(visit)
    return by_phone, by_name, by_user


def _identity_related(left: PmoVaccinationVisit, right: PmoVaccinationVisit) -> bool:
    """Nome compatível OU telefone em comum: o mínimo para ser a mesma casa."""
    if _names_compatible(left, right):
        return True
    return bool(_phone_keys(left) & _phone_keys(right))


def _matching_visits(
    master_visit: PmoVaccinationVisit,
    *,
    by_phone,
    by_name,
    by_user,
) -> list[PmoVaccinationVisit]:
    matches: dict[int, PmoVaccinationVisit] = {}
    if master_visit.tutor_user_id:
        for visit in by_user.get(master_visit.tutor_user_id, []):
            # A conta do tutor sozinha não basta: vínculos errados herdados de
            # syncs antigos (quando duas famílias eram fundidas na mesma conta)
            # colocariam o "Vacinado" de uma casa na linha da outra. Exigimos
            # que nome ou telefone também batam — o que é grátis para os
            # vínculos corretos, porque a conta só é reusada quando telefone E
            # nome conferem.
            if not _identity_related(master_visit, visit):
                continue
            matches[visit.id] = visit
    for key in _phone_keys(master_visit):
        for visit in by_phone.get(key, []):
            same_user = bool(master_visit.tutor_user_id) and visit.tutor_user_id == master_visit.tutor_user_id
            if same_user or _names_compatible(master_visit, visit):
                matches[visit.id] = visit
    name_key = _name_key(master_visit)
    if name_key:
        for visit in by_name.get(name_key, []):
            matches[visit.id] = visit
    return sorted(matches.values(), key=_sheet_sort_key)


def _overall_status(matches: list[PmoVaccinationVisit]) -> str:
    if not matches:
        return "sem_registro"
    today = date.today()
    statuses = [infer_visit_status(visit.animals) for visit in matches]
    dated_statuses = [
        infer_visit_status(visit.animals)
        for visit in matches
        if _parse_date_object((visit.sheet_title or "").strip())
    ]
    # Calculado antes do bloco dated para que Encaixes vermelho possa sobrescrever
    # status de abas datadas (ex.: pendente agendado → recusou).
    contextual_statuses = [_display_status_key(visit) for visit in matches]
    has_encaixes_recusou = any(
        _is_encaixes(visit) and infer_visit_status(visit.animals) == "recusou"
        for visit in matches
    )
    # Se há uma aba datada futura com animais pendentes, a pessoa já está reagendada.
    # Isso ganha sobre parcial/ausente/remarcar histórico (mas não sobre vacinado).
    has_future_pendente = any(
        infer_visit_status(visit.animals) == "pendente"
        and (sheet_date := _parse_date_object((visit.sheet_title or "").strip()))
        and sheet_date >= today
        for visit in matches
    )
    if dated_statuses:
        if any(status == "vacinado" for status in dated_statuses):
            return "vacinado"
        # Aba futura com pendente = de volta no fluxo, independente de histórico parcial/ausente.
        if has_future_pendente:
            return "agendado"
        if any(status == "parcial" for status in dated_statuses):
            # Encaixes vermelho + aba datada parcial = parcial encerrado (laranja).
            return "parcial_encerrado" if has_encaixes_recusou else "parcial"
        if any(status == "remarcar" for status in dated_statuses):
            return "remarcar"
        if any(status == "recusou" for status in dated_statuses):
            return "recusou"
        if any(status == "ausente" for status in dated_statuses):
            return "ausente"
        # Encaixes vermelho ganha sobre "agendado": tutor recusou o contato.
        if has_encaixes_recusou:
            return "recusou"
        if any(status == "pendente" for status in dated_statuses):
            return "agendado"
    if any(status == "vacinado" for status in statuses):
        return "vacinado"
    for status in ("recusou", "perdeu_contato", "fluxo_ativo", "reagendar"):
        if status in contextual_statuses:
            return status
    return "pendente"


def _display_status_key(visit: PmoVaccinationVisit) -> str:
    status = infer_visit_status(visit.animals)
    if _is_inscricao_a_agendar(visit) and status == "pendente":
        return "fluxo_ativo"
    if not _is_encaixes(visit):
        return status
    if status == "recusou":
        return "recusou"
    if status in {"ausente", "parcial"}:
        return "perdeu_contato"
    if status in {"remarcar", "vacinado"}:
        return "reagendar"
    return "reagendar"


def _visit_sheet_url(visit: PmoVaccinationVisit) -> str:
    spreadsheet_id = visit.spreadsheet_id or _extract_google_sheet_id(DEFAULT_SHEET_URL)
    if not spreadsheet_id or not visit.sheet_gid or not visit.source_row:
        return ""
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        f"#gid={visit.sheet_gid}&range=A{visit.source_row}"
    )


def _visit_line(visit: PmoVaccinationVisit) -> str:
    status = _display_status_key(visit)
    row_label = f"linha {visit.source_row}" if visit.source_row else "linha ?"
    animals = "; ".join(
        f"{animal.name}: {STATUS_LABELS.get(animal.status or 'pendente', animal.status or 'pendente')}"
        for animal in visit.animals
    ) or _animal_names(visit)
    date_label = ""
    if visit.vaccine_date:
        date_label = f" em {visit.vaccine_date.strftime('%d/%m/%Y')}"
    return (
        f"- {visit.sheet_title} ({row_label}): "
        f"{STATUS_LABELS.get(status, status)}{date_label}. Pets: {animals}"
    )


def _status_link_cell(matches: list[PmoVaccinationVisit]) -> tuple[str, list[dict[str, Any]]]:
    overall = _overall_status(matches)
    if not matches:
        return STATUS_LABELS.get(overall, "Sem registro"), []

    text_parts = [STATUS_LABELS.get(overall, overall)]
    runs: list[dict[str, Any]] = []
    for visit in matches[:8]:
        status = _display_status_key(visit)
        row_label = f"linha {visit.source_row}" if visit.source_row else "linha ?"
        date_label = f" - {visit.vaccine_date.strftime('%d/%m/%Y')}" if visit.vaccine_date else ""
        text_parts.append("\n")
        start_index = sum(len(part) for part in text_parts)
        sheet_label = visit.sheet_title or "Aba"
        text_parts.append(sheet_label)
        url = _visit_sheet_url(visit)
        if url:
            runs.append(
                {
                    "startIndex": start_index,
                    "format": {
                        "link": {"uri": url},
                        "foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.8},
                        "underline": True,
                    },
                }
            )
            runs.append({"startIndex": start_index + len(sheet_label), "format": {}})
        text_parts.append(f" ({row_label}): {STATUS_LABELS.get(status, status)}{date_label}")
    if len(matches) > 8:
        text_parts.append(f"\n+{len(matches) - 8} outros")
    return "".join(text_parts), runs


def _build_note(master_visit: PmoVaccinationVisit, matches: list[PmoVaccinationVisit]) -> str:
    overall = _overall_status(matches)
    lines = [
        "PetOrlandia PMO",
        f"Tutor: {master_visit.tutor_name}",
        f"Status geral: {STATUS_LABELS.get(overall, 'Sem registro em outras abas')}",
        f"Pets no cadastro: {_animal_names(master_visit)}",
    ]
    if master_visit.requested_date:
        lines.append(f"Solicitação: {master_visit.requested_date.strftime('%d/%m/%Y')}")
    if not matches:
        lines.append("")
        lines.append("Ainda não localizado nas abas de agendamento, encaixe ou vacinação.")
        return "\n".join(lines)

    scheduled = [
        visit for visit in matches
        if _normalize_text_key(visit.sheet_title or "") in _tracked_non_date_titles()
    ]
    dated = [
        visit for visit in matches
        if _parse_date_object((visit.sheet_title or "").strip())
    ]
    if scheduled:
        lines.append("")
        lines.append("Aparece em abas de fila/agendamento:")
        for visit in scheduled[:8]:
            lines.append(_visit_line(visit))
    if dated:
        lines.append("")
        lines.append("Aparece em abas com data:")
        for visit in dated[:12]:
            lines.append(_visit_line(visit))
    if len(matches) > 20:
        lines.append(f"... +{len(matches) - 20} registros relacionados")
    return "\n".join(lines)


def _build_legend_requests(sheet_id: int) -> list[dict[str, Any]]:
    rows = []
    for row_index, legend_row in enumerate(LEGEND_ROWS):
        values = []
        for text in legend_row:
            cell = {
                "userEnteredValue": {"stringValue": text},
                "userEnteredFormat": {
                    "wrapStrategy": "WRAP",
                    "verticalAlignment": "MIDDLE",
                },
            }
            if row_index == 0:
                cell["userEnteredFormat"]["textFormat"] = {"bold": True}
                cell["userEnteredFormat"]["backgroundColor"] = {"red": 0.851, "green": 0.918, "blue": 0.827}
            values.append(cell)
        rows.append({"values": values})

    requests = [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": LEGEND_START_COLUMN_INDEX,
                    "endIndex": LEGEND_END_COLUMN_INDEX,
                },
                "properties": {"pixelSize": 190},
                "fields": "pixelSize",
            }
        },
        {
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": len(LEGEND_ROWS),
                    "startColumnIndex": LEGEND_START_COLUMN_INDEX,
                    "endColumnIndex": LEGEND_END_COLUMN_INDEX,
                },
                "rows": rows,
                "fields": (
                    "userEnteredValue,"
                    "userEnteredFormat.backgroundColor,"
                    "userEnteredFormat.textFormat,"
                    "userEnteredFormat.verticalAlignment,"
                    "userEnteredFormat.wrapStrategy"
                ),
            }
        },
    ]
    for row_index, color in enumerate(LEGEND_SWATCH_COLORS):
        if row_index == 0 or color is None:
            continue
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_index,
                        "endRowIndex": row_index + 1,
                        "startColumnIndex": LEGEND_START_COLUMN_INDEX,
                        "endColumnIndex": LEGEND_START_COLUMN_INDEX + 1,
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": color}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
        )
    return requests


def _ensure_master_columns(service, spreadsheet_id: str, sheet_id: int) -> None:
    """Garante que a aba mestre tenha colunas suficientes (até a legenda).

    Se o usuário apagar colunas (ex.: a M de Status), o batchUpdate falharia com
    'Cannot update a column that doesn't exist'. Aqui estendemos a grade antes.
    """
    needed = LEGEND_END_COLUMN_INDEX + 1
    meta = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(sheetId,gridProperties(columnCount)))",
        )
        .execute()
    )
    current = None
    for sheet in meta.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("sheetId") == sheet_id:
            current = (props.get("gridProperties") or {}).get("columnCount")
            break
    if current is not None and current < needed:
        _retry_execute(
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "appendDimension": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "length": needed - current,
                            }
                        }
                    ]
                },
            )
        )


PMO_NOTE_HEADER = "PetOrlandia PMO"
_NOTE_TUTOR_RE = re.compile(r"^Tutor:\s*(.+)$", re.MULTILINE)


def _cell_note(row: list[Any], index: int) -> str:
    if index >= len(row):
        return ""
    cell = row[index] if isinstance(row[index], dict) else {}
    return str(cell.get("note") or "").strip()


def _note_tutor(note: str) -> str:
    """Tutor de uma nota escrita por este script (vazio se a nota não é nossa)."""
    if not note or not note.lstrip().startswith(PMO_NOTE_HEADER):
        return ""
    match = _NOTE_TUTOR_RE.search(note)
    return match.group(1).strip() if match else ""


_TIMESTAMP_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}[\s,]+\d{1,2}:\d{2}")


def _identity_offset(values: list[str]) -> int:
    """Quantas colunas antes do nome do tutor.

    ``_row_column_offset`` só reconhece a coluna de carimbo quando ela é uma
    data pura; o formulário grava data E hora ("17/08/2026 14:42:13"). Como
    esta função serve para CONFERIR a linha, ela aceita as duas grafias — e o
    reconhecimento continua tentando os dois offsets em ``_row_identity``.
    """
    offset = _row_column_offset(values)
    if offset:
        return 1
    first = values[0] if values else ""
    second = values[1] if len(values) > 1 else ""
    if second and _TIMESTAMP_RE.match(first.strip()):
        return 1
    return 0


def _row_identity(row: list[Any]) -> dict[str, Any]:
    """Quem está NA LINHA da planilha agora: nome, telefones e nota já gravada.

    Nome e telefone são coletados nos DOIS offsets possíveis (com e sem coluna
    de carimbo). Conferir é o objetivo: aceitar as duas leituras evita recusar
    uma linha correta só porque o carimbo mudou de formato, e continua
    recusando a linha de outro tutor — nome e telefone de outra casa não batem
    em nenhum dos offsets.
    """
    values = _row_values(row)
    offset = _identity_offset(values)
    name = values[0 + offset] if len(values) > offset else ""
    names = [
        values[index]
        for index in (offset, 1 - offset)
        if len(values) > index and values[index]
    ]
    phones: set[str] = set()
    for index in (5, 6, 7):
        if len(values) > index:
            phones |= _phone_digit_keys(values[index])
    note = _cell_note(row, TIMESTAMP_COLUMN_INDEX)
    status_text = (
        values[STATUS_LINK_COLUMN_INDEX]
        if len(values) > STATUS_LINK_COLUMN_INDEX
        else ""
    )
    return {
        "name": name,
        "name_key": _normalize_text_key(name),
        "names": names,
        "phone_keys": phones,
        "has_note": bool(note),
        "note_tutor": _note_tutor(note),
        "status_text": status_text,
    }


def _master_row_identities(
    service,
    spreadsheet_id: str,
    *,
    sheet_title: str = MASTER_SHEET_TITLE,
    sheet_gid: str = "",
) -> dict[int, dict[str, Any]]:
    """Releitura da aba mestre para conferir cada linha ANTES de escrever nela.

    O banco guarda ``source_row``, mas a planilha é reordenada e reescrita pela
    equipe (o menu "Otimizar Rotas por Cluster" limpa e regrava a aba inteira) e
    linhas incompletas não voltam do parser. Quando a posição no banco envelhece,
    escrever pelo número da linha carimba o status de um tutor na linha de outro
    — foi exatamente o "já vacinado em 20/08" que apareceu no cadastro errado.
    Com esta leitura, cada escrita é conferida contra quem está na linha agora.
    """
    rows = _fetch_sheet_rows(service, spreadsheet_id, sheet_title, sheet_gid)
    identities: dict[int, dict[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        if index == 1:
            continue  # cabeçalho
        identity = _row_identity(row)
        if (
            not identity["name_key"]
            and not identity["note_tutor"]
            and not identity["status_text"]
        ):
            continue
        identities[index] = identity
    return identities


def _row_matches_visit(identity: dict[str, Any] | None, visit: PmoVaccinationVisit) -> bool:
    """A linha da planilha ainda é a mesma casa do registro do banco?"""
    if not identity:
        return False
    tutor_name = visit.tutor_name or ""
    names_ok = any(
        _name_texts_compatible(name, tutor_name) for name in identity.get("names", [])
    )
    row_phones = _strong_phone_keys(identity["phone_keys"])
    visit_phones = _strong_phone_keys(_phone_keys(visit))
    if row_phones and visit_phones:
        # Com telefone dos dois lados, nome compatível não basta: dois "Maria"
        # na mesma rua têm nomes compatíveis e casas diferentes, e aceitar pelo
        # nome poria o "Vacinado" de uma na linha da outra. Telefone que não
        # bate é contradição, não falta de informação.
        return names_ok and bool(row_phones & visit_phones)
    # Só um dos lados tem telefone utilizável (fixo sem DDD, célula vazia): aí
    # o nome é a única prova disponível.
    return names_ok


def _status_text_is_ours(text: str) -> bool:
    """O texto da coluna M foi escrito por este script.

    O formato é sempre "<Status geral>\n<Aba> (linha N): <status>". Não diz de
    QUEM é — por isso só serve para reconhecer sobra nossa, nunca para decidir
    dono.
    """
    stripped = (text or "").strip()
    if not stripped or "(linha " not in stripped:
        return False
    first_line = stripped.splitlines()[0].strip()
    return first_line in set(STATUS_LABELS.values()) | {"Sem registro"}


def _note_is_foreign(identity: dict[str, Any]) -> bool:
    """A nota gravada por nós fala de um tutor que não é o dono da linha."""
    note_tutor = identity.get("note_tutor") or ""
    if not note_tutor:
        return False
    names = identity.get("names") or []
    if not names:
        return True  # linha esvaziada com nota nossa sobrando
    return not any(_name_texts_compatible(note_tutor, name) for name in names)


def _plan_master_rows(
    master_visits: list[PmoVaccinationVisit],
    row_identities: dict[int, dict[str, Any]] | None,
    summary: Counter | None = None,
) -> list[tuple[int, PmoVaccinationVisit]]:
    """Em que linha cada visita da aba mestre pode ser escrita com segurança.

    Sem ``row_identities`` (uso avulso do script, ou falha ao reler a planilha)
    mantém o comportamento antigo: confia no ``source_row`` do banco.
    """
    if not row_identities:
        return [
            (visit.source_row, visit)
            for visit in master_visits
            if (visit.source_row or 0) > 0
        ]

    counters = summary if summary is not None else Counter()
    claimed: dict[int, PmoVaccinationVisit] = {}
    pending: list[PmoVaccinationVisit] = []

    for visit in master_visits:
        row = visit.source_row or 0
        if row <= 0:
            continue
        if row in claimed:
            pending.append(visit)
            continue
        if _row_matches_visit(row_identities.get(row), visit):
            claimed[row] = visit
        else:
            pending.append(visit)

    rows_by_name: dict[str, list[int]] = defaultdict(list)
    rows_by_phone: dict[str, list[int]] = defaultdict(list)
    for row, identity in row_identities.items():
        if identity["name_key"]:
            rows_by_name[identity["name_key"]].append(row)
        for key in _strong_phone_keys(identity["phone_keys"]):
            rows_by_phone[key].append(row)

    for visit in pending:
        # O nome na planilha pode ter sido abreviado ("Raquel F." no banco,
        # "Raquel Feliciano" na aba): procurar só pela chave exata deixaria a
        # linha certa de fora. O telefone entra como segunda porta de entrada e
        # quem decide continua sendo _row_matches_visit.
        possiveis: set[int] = set(rows_by_name.get(_name_key(visit), []))
        for key in _strong_phone_keys(_phone_keys(visit)):
            possiveis.update(rows_by_phone.get(key, []))
        candidates = [
            row
            for row in sorted(possiveis)
            if row not in claimed and _row_matches_visit(row_identities[row], visit)
        ]
        if len(candidates) == 1:
            claimed[candidates[0]] = visit
            counters["linhas_realinhadas"] += 1
        else:
            counters["linhas_ignoradas_divergentes"] += 1

    return sorted(claimed.items())


def _clear_row_requests(sheet_id: int, row_number: int) -> list[dict[str, Any]]:
    """Apaga uma nota/status nossos que ficaram numa linha de outro tutor."""
    return [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_number - 1,
                    "endRowIndex": row_number,
                    "startColumnIndex": TIMESTAMP_COLUMN_INDEX,
                    "endColumnIndex": TIMESTAMP_COLUMN_INDEX + 1,
                },
                "cell": {
                    "note": "",
                    "userEnteredFormat": {"backgroundColor": PMO_STATUS_CLEAR_COLOR},
                },
                "fields": "note,userEnteredFormat.backgroundColor",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_number - 1,
                    "endRowIndex": row_number,
                    "startColumnIndex": STATUS_LINK_COLUMN_INDEX,
                    "endColumnIndex": STATUS_LINK_COLUMN_INDEX + 1,
                },
                "cell": {
                    "userEnteredValue": {"stringValue": ""},
                    "userEnteredFormat": {"backgroundColor": PMO_STATUS_CLEAR_COLOR},
                },
                "fields": (
                    "userEnteredValue,textFormatRuns,"
                    "userEnteredFormat.backgroundColor"
                ),
            }
        },
    ]


def _safe_master_row_identities(
    service,
    spreadsheet_id: str,
    *,
    sheet_title: str = MASTER_SHEET_TITLE,
    sheet_gid: str = "",
    logger=None,
) -> dict[int, dict[str, Any]] | None:
    """Identidades das linhas da aba mestre, ou ``None`` se a leitura falhar.

    Falhar a releitura não pode travar a sincronização inteira: sem ela o script
    volta ao comportamento antigo (escreve pelo ``source_row``). Uma leitura que
    volta vazia também vira ``None`` — planilha vazia de verdade não tem o que
    escrever, e leitura truncada não deve virar "todas as linhas divergem".
    """
    try:
        identities = _master_row_identities(
            service, spreadsheet_id, sheet_title=sheet_title, sheet_gid=sheet_gid
        )
    except Exception:
        message = "[PMO] Falha ao reler a aba mestre para conferir as linhas."
        if logger is not None:
            logger.exception(message)
        else:
            print(message)
        return None
    return identities or None


def _build_requests(
    sheet_id: int,
    master_visits: list[PmoVaccinationVisit],
    match_map: dict[int, list[PmoVaccinationVisit]],
    *,
    row_identities: dict[int, dict[str, Any]] | None = None,
    summary: Counter | None = None,
):
    requests = _build_legend_requests(sheet_id) + [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": STATUS_LINK_COLUMN_INDEX,
                    "endIndex": STATUS_LINK_COLUMN_INDEX + 1,
                },
                "properties": {"pixelSize": 260},
                "fields": "pixelSize",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": STATUS_LINK_COLUMN_INDEX,
                    "endColumnIndex": STATUS_LINK_COLUMN_INDEX + 1,
                },
                "cell": {
                    "userEnteredValue": {"stringValue": "Status PMO"},
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.851, "green": 0.918, "blue": 0.827},
                    },
                },
                "fields": "userEnteredValue,userEnteredFormat.textFormat,userEnteredFormat.backgroundColor",
            }
        },
    ]
    counters = summary if summary is not None else Counter()
    plan = _plan_master_rows(master_visits, row_identities, counters)
    written_rows: set[int] = set()
    for row_number, visit in plan:
        matches = match_map.get(visit.id, [])
        status = _overall_status(matches)
        status_text, status_runs = _status_link_cell(matches)
        # Sem correspondência: NÃO sobrescreve a linha — preserva o que já está na
        # coluna M (e na coluna A). Antes, linhas sem match recebiam "Sem registro"
        # com cor neutra, apagando o status compilado que já existia ali.
        if not matches:
            continue
        written_rows.add(row_number)
        counters["linhas_escritas"] += 1
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_number - 1,
                        "endRowIndex": row_number,
                        "startColumnIndex": TIMESTAMP_COLUMN_INDEX,
                        "endColumnIndex": TIMESTAMP_COLUMN_INDEX + 1,
                    },
                    "cell": {
                        "note": _build_note(visit, matches),
                        "userEnteredFormat": {
                            "backgroundColor": STATUS_COLORS.get(status, PMO_STATUS_CLEAR_COLOR),
                            "numberFormat": {
                                "type": "DATE_TIME",
                                "pattern": "dd/MM/yyyy HH:mm:ss",
                            },
                        },
                    },
                    "fields": "note,userEnteredFormat.backgroundColor,userEnteredFormat.numberFormat",
                }
            }
        )
        status_cell = {
            "userEnteredValue": {"stringValue": status_text},
            "userEnteredFormat": {
                "backgroundColor": STATUS_COLORS.get(status, PMO_STATUS_CLEAR_COLOR),
                "wrapStrategy": "WRAP",
            },
        }
        if status_runs:
            status_cell["textFormatRuns"] = status_runs
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_number - 1,
                        "endRowIndex": row_number,
                        "startColumnIndex": STATUS_LINK_COLUMN_INDEX,
                        "endColumnIndex": STATUS_LINK_COLUMN_INDEX + 1,
                    },
                    "cell": status_cell,
                    "fields": "userEnteredValue,textFormatRuns,userEnteredFormat.backgroundColor,userEnteredFormat.wrapStrategy",
                }
            }
        )

    # Linhas que ficaram com a nota de OUTRO tutor (a planilha foi reordenada
    # depois da última escrita) e que ninguém vai reescrever agora: limpar é o
    # que impede a equipe de ler "já vacinado" no cadastro errado.
    for row_number, identity in sorted((row_identities or {}).items()):
        if row_number in written_rows:
            continue
        # Nota nossa nomeando outro tutor: sobra certa de uma reordenação.
        foreign_note = _note_is_foreign(identity)
        # Status nosso na coluna M sem nota nenhuma na coluna A: as duas
        # coisas são sempre escritas juntas, então um M sozinho é sobra de uma
        # gravação cuja linha mudou de dono. Quando a nota existe e é do
        # próprio tutor, nada é tocado.
        orphan_status = (
            not identity.get("has_note")
            and _status_text_is_ours(identity.get("status_text", ""))
        )
        if not foreign_note and not orphan_status:
            continue
        requests.extend(_clear_row_requests(sheet_id, row_number))
        counters["linhas_limpas"] += 1

    return requests


def _chunked(items: list[dict[str, Any]], size: int):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Grava notas e cores na aba Vacinação 2026.")
    parser.add_argument("--limit", type=int, default=0, help="Limita linhas da aba mestre para teste.")
    parser.add_argument("--skip-sync", action="store_true", help="Usa o banco como está, sem reler as abas.")
    args = parser.parse_args()

    with app.app_context():
        service = _get_sheets_service_rw()
        spreadsheet_id = _extract_google_sheet_id(DEFAULT_SHEET_URL)
        if not spreadsheet_id:
            raise RuntimeError("Planilha PMO inválida.")

        if args.skip_sync:
            synced_sheets, synced_rows = 0, 0
        else:
            synced_sheets, synced_rows = _sync_relevant_sheets()
        master_visits = (
            PmoVaccinationVisit.query
            .filter(PmoVaccinationVisit.sheet_title == MASTER_SHEET_TITLE)
            .order_by(PmoVaccinationVisit.source_row.asc())
            .all()
        )
        if args.limit:
            master_visits = master_visits[:args.limit]
        all_visits = PmoVaccinationVisit.query.all()
        by_phone, by_name, by_user = _build_visit_index(all_visits)
        match_map = {
            visit.id: _matching_visits(visit, by_phone=by_phone, by_name=by_name, by_user=by_user)
            for visit in master_visits
        }
        status_counts = Counter(_overall_status(matches) for matches in match_map.values())
        matched_count = sum(1 for matches in match_map.values() if matches)

        sheet_ids = _resolve_sheet_id_by_title(service, spreadsheet_id)
        master_sheet_id = sheet_ids.get(MASTER_SHEET_TITLE)
        if master_sheet_id is None:
            raise RuntimeError(f"Aba {MASTER_SHEET_TITLE!r} não encontrada.")

        row_identities = _safe_master_row_identities(service, spreadsheet_id)
        row_counters: Counter = Counter()
        requests = _build_requests(
            master_sheet_id,
            master_visits,
            match_map,
            row_identities=row_identities,
            summary=row_counters,
        )
        if args.apply and requests:
            for chunk in _chunked(requests, 200):
                _retry_execute(
                    service.spreadsheets().batchUpdate(
                        spreadsheetId=spreadsheet_id,
                        body={"requests": chunk},
                    )
                )

        print(f"abas_sincronizadas: {synced_sheets}")
        print(f"linhas_sincronizadas: {synced_rows}")
        print(f"linhas_mestre: {len(master_visits)}")
        print(f"linhas_com_match: {matched_count}")
        print(f"notas_preparadas: {len(requests)}")
        print(f"conferencia_de_linha: {bool(row_identities)}")
        print(f"aplicado: {bool(args.apply)}")
        for key, count in sorted(row_counters.items()):
            print(f"{key}: {count}")
        for status, count in sorted(status_counts.items()):
            print(f"status_{status}: {count}")


if __name__ == "__main__":
    main()
