"""Rotas para exportação fiscal."""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta

from flask import abort, make_response, request
from flask_login import current_user, login_required
from sqlalchemy import func

from helpers import has_veterinarian_profile
from models import FiscalDocument, FiscalDocumentStatus, FiscalDocumentType


def _current_user_clinic_id():
    if not current_user.is_authenticated:
        return None
    if has_veterinarian_profile(current_user):
        return getattr(current_user.veterinario, "clinica_id", None)
    return current_user.clinica_id


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Data inválida.") from exc


def _build_filename(document: FiscalDocument, used_names: set[str]) -> str:
    doc_type = document.doc_type.value.lower() if document.doc_type else "fiscal"
    identifier = document.nfse_number or document.access_key or document.id
    base = f"{doc_type}-{identifier}.xml"
    filename = base
    counter = 1
    while filename in used_names:
        counter += 1
        filename = f"{doc_type}-{identifier}-{counter}.xml"
    used_names.add(filename)
    return filename


@login_required
def fiscal_exports_xmls():
    clinic_id = _current_user_clinic_id()
    if not clinic_id:
        abort(403)

    start_date_raw = request.args.get("start_date")
    end_date_raw = request.args.get("end_date")
    doc_type_raw = request.args.get("doc_type")

    query = FiscalDocument.query.filter_by(clinic_id=clinic_id)
    query = query.filter(FiscalDocument.status == FiscalDocumentStatus.AUTHORIZED)
    query = query.filter(FiscalDocument.xml_authorized.isnot(None))

    if doc_type_raw:
        try:
            doc_type = FiscalDocumentType[doc_type_raw.upper()]
            query = query.filter(FiscalDocument.doc_type == doc_type)
        except KeyError:
            abort(400, "Tipo de documento inválido.")

    try:
        start_dt = _parse_date(start_date_raw)
        end_dt = _parse_date(end_date_raw)
    except ValueError as exc:
        abort(400, str(exc))

    timestamp_field = func.coalesce(FiscalDocument.authorized_at, FiscalDocument.created_at)
    if start_dt:
        query = query.filter(timestamp_field >= start_dt)
    if end_dt:
        query = query.filter(timestamp_field < end_dt + timedelta(days=1))

    documents = query.order_by(timestamp_field.desc()).all()
    if not documents:
        abort(404)

    buffer = io.BytesIO()
    used_names: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for document in documents:
            if not document.xml_authorized:
                continue
            filename = _build_filename(document, used_names)
            zip_file.writestr(filename, document.xml_authorized)

    if not used_names:
        abort(404)

    buffer.seek(0)
    start_label = start_dt.strftime("%Y%m%d") if start_dt else "inicio"
    end_label = end_dt.strftime("%Y%m%d") if end_dt else "hoje"
    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "application/zip"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=xmls-fiscais-{start_label}-{end_label}.zip"
    )
    return response
