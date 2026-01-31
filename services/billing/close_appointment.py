from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from models import Appointment, FiscalDocument, FiscalDocumentType
from services.fiscal.nfe_service import (
    create_nfe_document_for_appointment,
    queue_emit_nfe,
)
from services.fiscal.nfse_service import (
    build_nfse_payload_from_appointment,
    create_nfse_document,
    queue_emit_nfse,
)


@dataclass(frozen=True)
class CloseAppointmentDocuments:
    nfse_document: FiscalDocument | None = None
    nfe_document: FiscalDocument | None = None


def close_appointment(appointment: Appointment) -> CloseAppointmentDocuments:
    if not appointment or not appointment.clinica or not appointment.clinica.fiscal_emitter:
        return CloseAppointmentDocuments()

    consulta = appointment.consulta
    items = list(consulta.orcamento_items) if consulta and consulta.orcamento_items else []
    service_items = [item for item in items if item.servico_id]
    product_items = [item for item in items if not item.servico_id]

    nfse_document = None
    nfe_document = None

    if service_items:
        nfse_document = _latest_document(appointment.id, FiscalDocumentType.NFSE)
        if not nfse_document:
            payload = build_nfse_payload_from_appointment(appointment)
            service_total = sum((item.valor for item in service_items), start=Decimal("0.00"))
            payload.setdefault("servico", {})["valor"] = float(service_total)
            payload.setdefault("source", {}).update(
                {
                    "service_item_ids": [item.id for item in service_items],
                    "consulta_id": appointment.consulta_id,
                }
            )
            nfse_document = create_nfse_document(
                related_type="appointment",
                related_id=appointment.id,
                emitter_id=appointment.clinica.fiscal_emitter.id,
                payload=payload,
            )
            queue_emit_nfse(nfse_document.id)

    if product_items:
        nfe_document = _latest_document(appointment.id, FiscalDocumentType.NFE)
        if not nfe_document:
            payload = _build_nfe_payload_from_appointment(appointment, product_items)
            nfe_document = create_nfe_document_for_appointment(
                appointment_id=appointment.id,
                emitter_id=appointment.clinica.fiscal_emitter.id,
                payload=payload,
            )
            queue_emit_nfe(nfe_document.id)

    return CloseAppointmentDocuments(
        nfse_document=nfse_document,
        nfe_document=nfe_document,
    )


def _latest_document(appointment_id: int, doc_type: FiscalDocumentType) -> FiscalDocument | None:
    return (
        FiscalDocument.query.filter_by(
            related_type="appointment",
            related_id=appointment_id,
            doc_type=doc_type,
        )
        .order_by(FiscalDocument.created_at.desc())
        .first()
    )


def _build_nfe_payload_from_appointment(appointment: Appointment, items: list) -> dict:
    tutor = appointment.tutor
    if not tutor and appointment.animal:
        tutor = appointment.animal.owner

    clinic = appointment.clinica
    endereco_texto = (tutor.address or "").strip() if tutor else ""
    dest = {
        "CPF": getattr(tutor, "cpf", None) if tutor else None,
        "xNome": tutor.name if tutor else "Consumidor final",
        "enderDest": {
            "xLgr": endereco_texto or "Endereço não informado",
            "nro": "S/N",
            "xBairro": "Centro",
            "cMun": clinic.municipio_ibge if clinic else "",
            "xMun": (clinic.endereco_json or {}).get("cidade") if clinic else None,
            "UF": clinic.uf if clinic else None,
            "CEP": (clinic.endereco_json or {}).get("cep") if clinic else None,
            "cPais": "1058",
            "xPais": "BRASIL",
        },
        "indIEDest": "9",
    }

    payload_items = [
        {
            "code": f"APPT-{appointment.id}-{item.id}",
            "name": item.descricao,
            "quantity": 1,
            "unit_price": float(item.valor),
            "ncm": "00000000",
            "cfop": "5102",
            "unit": "UN",
        }
        for item in items
    ]

    return {
        "appointment_id": appointment.id,
        "consulta_id": appointment.consulta_id,
        "dest": dest,
        "items": payload_items,
        "inf_adic": f"Venda vinculada ao atendimento #{appointment.id}.",
    }
