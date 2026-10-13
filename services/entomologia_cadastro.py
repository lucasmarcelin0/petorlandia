"""Read the private cadastral pilot for the administrator-only map endpoints.

The HTTP caller must authorize the logged-in administrator before calling these
helpers. This module never reads the offline preview, publishes files, geocodes
addresses, logs personal values, or retains them in a process-wide cache.
"""

from __future__ import annotations

import json
import hashlib
import os
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_RECORDS = 50_000
MAX_OWNER_FIELDS = 100
MAX_TEXT_LENGTH = 4_000
MAX_QUERY_LENGTH = 200
MAX_RESULTS = 50
CADASTRO_IMPORT_TYPE = "cadastro_privado"
CADASTRO_IMPORT_TITLE = "Cadastro privado de imóveis (Betha)"
PROPERTY_FIELDS = (
    "property_code", "registration", "address", "owner_name", "owner_code",
    "registry_number",
)
OWNER_FIELDS = (
    "owner_code", "owner_name", "status", "collected_at", "source_url", "fields",
)


class _InvalidCadastre(ValueError):
    """Internal validation failure; messages contain no source values."""


def _text(value: object, *, required: bool = False, limit: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise _InvalidCadastre("Invalid text field")
    if required and not value.strip():
        raise _InvalidCadastre("Missing required text field")
    if "\x00" in value:
        raise _InvalidCadastre("Invalid text field")
    return value


def _code(value: object) -> str:
    text = _text(value, required=True, limit=80)
    if text != text.strip() or any(unicodedata.category(c) == "Cc" for c in text):
        raise _InvalidCadastre("Invalid identifier")
    return text


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidCadastre("Duplicate JSON key")
        result[key] = value
    return result


def _safe_source_url(value: str) -> str:
    """Keep ordinary Betha navigation links; never return signed/token URLs."""
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or parts.hostname not in {
                "atendimento-tributos.betha.cloud", "tributos.betha.cloud",
            }
            or parts.username or parts.password or parts.query
            or "?" in parts.fragment
        ):
            return ""
        normalized = value.casefold()
        if any(term in normalized for term in (
            "token", "authorization", "signature", "download", "resultado",
        )):
            return ""
        return value
    except ValueError:
        return ""


def _configured_path() -> Path | None:
    configured = current_app.config.get("SFA_CADASTRO_PATH")
    if configured is None:
        configured = os.environ.get("SFA_CADASTRO_PATH")
    if configured is None:
        return None
    if not isinstance(configured, (str, os.PathLike)) or not str(configured).strip():
        raise _InvalidCadastre("Invalid private file configuration")
    path = Path(configured)
    if not path.is_absolute():
        path = Path(current_app.instance_path) / path
    path = path.resolve()
    # A mistaken configuration must not turn a public static asset into the
    # personal-data source. Resolve symlinks before checking containment.
    static_dir = current_app.static_folder
    if static_dir is not None:
        static_path = Path(static_dir).resolve()
        if path == static_path or static_path in path.parents:
            raise _InvalidCadastre("Public source forbidden")
    return path


def _decode_and_validate(contents: bytes) -> dict | None:
    try:
        if len(contents) > MAX_FILE_BYTES:
            return None
        source = json.loads(contents.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
        if not isinstance(source, dict):
            raise _InvalidCadastre("Invalid source object")
        collected_at = _text(source.get("collected_at"), required=True, limit=80)
        scope = _text(source.get("collection_scope"), required=True)
        source_records = source.get("records")
        source_owners = source.get("owners", [])
        if (
            not isinstance(source_records, list) or not source_records
            or len(source_records) > MAX_RECORDS
            or not isinstance(source_owners, list) or len(source_owners) > MAX_RECORDS
        ):
            raise _InvalidCadastre("Invalid collection")

        records, codes = [], set()
        for record in source_records:
            if not isinstance(record, dict):
                raise _InvalidCadastre("Invalid property")
            normalized = {field: _text(record.get(field)) for field in PROPERTY_FIELDS}
            normalized["property_code"] = _code(record.get("property_code"))
            normalized["owner_code"] = _code(record.get("owner_code"))
            _text(normalized["registration"], required=True)
            _text(normalized["address"], required=True)
            _text(normalized["owner_name"], required=True)
            if normalized["property_code"] in codes:
                raise _InvalidCadastre("Duplicate property identifier")
            codes.add(normalized["property_code"])
            records.append(normalized)

        owners = {}
        for owner in source_owners:
            if not isinstance(owner, dict) or not all(field in owner for field in OWNER_FIELDS):
                raise _InvalidCadastre("Invalid owner")
            code = _code(owner["owner_code"])
            if code in owners:
                raise _InvalidCadastre("Duplicate owner identifier")
            status = _text(owner["status"])
            if status not in {"consultado", "nao_consultado"}:
                raise _InvalidCadastre("Invalid owner status")
            fields = owner["fields"]
            if not isinstance(fields, list) or len(fields) > MAX_OWNER_FIELDS:
                raise _InvalidCadastre("Invalid owner fields")
            normalized_fields = []
            for field in fields:
                if not isinstance(field, dict):
                    raise _InvalidCadastre("Invalid owner field")
                normalized_fields.append({
                    "label": _text(field.get("label"), required=True, limit=200),
                    "value": _text(field.get("value")),
                })
            owners[code] = {
                "owner_code": code,
                "owner_name": _text(owner["owner_name"], required=True),
                "status": status,
                "collected_at": _text(owner["collected_at"], limit=80),
                "source_url": _safe_source_url(_text(owner["source_url"])),
                "fields": normalized_fields,
            }
        return {
            "records": records,
            "owners": owners,
            "metadata": {
                "records_count": len(records),
                "owners_count": len({record["owner_code"] for record in records}),
                "collected_at": collected_at,
                "scope": scope,
            },
        }
    except (OSError, ValueError, TypeError, RecursionError):
        # Do not disclose configuration, offending source values, or documents.
        return None


def validate_cadastro(contents: bytes) -> dict:
    """Validate an import with the same schema used by the private map reader."""
    if not isinstance(contents, bytes):
        raise ValueError("Cadastro privado inválido.")
    cadastro = _decode_and_validate(contents)
    if cadastro is None:
        raise ValueError("Cadastro privado inválido.")
    return cadastro


def _load_cadastro() -> dict | None:
    try:
        path = _configured_path()
        if path is not None:
            if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                return None
            with path.open("rb") as handle:
                contents = handle.read(MAX_FILE_BYTES + 1)
            return _decode_and_validate(contents)
        # Persisted snapshots stay in the database, behind the same strict
        # administrator authorization as the HTTP routes. Never consult a
        # preview/output file or a public atlas artifact as a fallback.
        from extensions import db
        from models.entomologia import EntomologiaImportacao

        if "sqlalchemy" not in current_app.extensions:
            return None
        with db.session.no_autoflush:
            rows = (EntomologiaImportacao.query
                    .filter_by(tipo=CADASTRO_IMPORT_TYPE, titulo=CADASTRO_IMPORT_TITLE, status="ATIVA")
                    .order_by(EntomologiaImportacao.id.desc()).limit(2).all())
        if len(rows) != 1:
            return None
        row = rows[0]
        if not isinstance(row.dados_json, str) or len(row.dados_json) > MAX_FILE_BYTES:
            return None
        contents = row.dados_json.encode("utf-8")
        if hashlib.sha256(contents).hexdigest() != row.sha256:
            return None
        return _decode_and_validate(contents)
    except SQLAlchemyError:
        from extensions import db

        db.session.rollback()
        return None
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def _normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return "".join(c for c in folded if not unicodedata.combining(c))


def search_cadastro(query: str | None, limit: int = 20) -> dict:
    """Return bounded property summaries; owner documents/contacts stay in detail.

    An empty or one-character query returns only metadata. All query words must
    match the property summary; accents and case are ignored. No owner personal
    fields are searchable or included in this response.
    """
    cadastro = _load_cadastro()
    if cadastro is None:
        return {
            "available": False,
            "metadata": {"records_count": 0, "owners_count": 0, "collected_at": "", "scope": ""},
            "results": [],
        }
    response = {"available": True, "metadata": cadastro["metadata"], "results": []}
    if not isinstance(query, str):
        return response
    query = query.strip()
    if len(query) < 2 or len(query) > MAX_QUERY_LENGTH:
        return response
    if isinstance(limit, bool):
        limit = 20
    try:
        bound = max(1, min(int(limit), MAX_RESULTS))
    except (ValueError, TypeError, OverflowError):
        bound = 20
    normalized_query = _normalize(query).strip()
    if len(normalized_query) < 2:
        return response
    tokens = normalized_query.split()
    for record in cadastro["records"]:
        searchable = _normalize(" ".join(record[field] for field in PROPERTY_FIELDS))
        if all(token in searchable for token in tokens):
            response["results"].append(dict(record))
            if len(response["results"]) >= bound:
                break
    return response


def get_cadastro_property(code: str) -> dict | None:
    """Return a property and its exact-code owner card, or None when unavailable."""
    if not isinstance(code, str) or not code or len(code) > 80:
        return None
    cadastro = _load_cadastro()
    if cadastro is None:
        return None
    for record in cadastro["records"]:
        if record["property_code"] == code:
            return {
                "property": dict(record),
                "owner": cadastro["owners"].get(record["owner_code"]),
                "metadata": cadastro["metadata"],
            }
    return None
