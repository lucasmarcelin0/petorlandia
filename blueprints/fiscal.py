"""Módulo fiscal (NFS-e, certificados, exportações) — views do domínio.

O wizard de onboarding e a exportação de XMLs já viviam em app/routes/*.py;
as rotas deles são registradas aqui importando as views via módulo app.
"""
from flask import Blueprint

bp = Blueprint("fiscal_routes", __name__)


def get_blueprint():
    return bp


def _register_app_routes_views():
    """Registra views hospedadas em app/routes/*.py (carregadas pelo app.py)."""
    import app as app_module

    bp.add_url_rule(
        "/fiscal/onboarding",
        view_func=app_module.fiscal_onboarding_start,
        methods=["GET"],
    )
    bp.add_url_rule(
        "/fiscal/onboarding/step/<int:step>",
        view_func=app_module.fiscal_onboarding_step,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/fiscal/exports/xmls",
        view_func=app_module.fiscal_exports_xmls,
        methods=["GET"],
    )


_register_app_routes_views()


import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from extensions import db
from models import (
    FiscalCertificate,
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalDocumentType,
    FiscalEmitter,
    FiscalEvent,
    get_clinica_field,
)
from security.crypto import encrypt_bytes, encrypt_text
from services.fiscal.certificate import parse_pfx
from document_utils import only_digits
from services.fiscal.nfse_service import (
    NFSE_NACIONAL_MUNICIPIO_IBGE,
    NFSE_NACIONAL_MUNICIPIO_IBGE_BY_KEY,
    VETERINARY_NFSE_SERVICE_DEFAULTS,
    cancel_nfse_document,
    create_manual_nfse_document,
    queue_emit_nfse,
)
from services.nfse_service import _normalize_municipio

from app import current_user_clinic_id


def _only_digits(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


FISCAL_UF_CODES = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
    "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}


def _normalize_cnpj(value: str | None) -> str:
    return only_digits(value)


def _validate_cnpj_format(value: str | None) -> bool:
    digits = _normalize_cnpj(value)
    return len(digits) == 14


def _normalize_uf(value: str | None) -> str:
    return (value or "").strip().upper()


def _manual_nfse_service_defaults(clinic) -> dict:
    if not clinic:
        return {}
    cnae_digits = _only_digits(str(get_clinica_field(clinic, "cnae", "") or ""))
    service_digits = _only_digits(str(get_clinica_field(clinic, "codigo_servico", "") or ""))
    if (
        cnae_digits == VETERINARY_NFSE_SERVICE_DEFAULTS["codigo_tributacao_municipal"]
        or service_digits == VETERINARY_NFSE_SERVICE_DEFAULTS["codigo_servico"]
    ):
        return dict(VETERINARY_NFSE_SERVICE_DEFAULTS)
    return {}


def _recent_nfse_tomadores(clinic_id: int) -> list[dict]:
    seen: dict[str, dict] = {}
    documents = (
        FiscalDocument.query
        .filter_by(clinic_id=clinic_id, doc_type=FiscalDocumentType.NFSE)
        .order_by(FiscalDocument.created_at.desc())
        .limit(200)
        .all()
    )
    for document in documents:
        payload = document.payload_json or {}
        tomador = payload.get("tomador") or {}
        doc_digits = _only_digits(
            tomador.get("cpf_cnpj")
            or tomador.get("cnpj")
            or tomador.get("cpf")
            or tomador.get("documento")
        )
        nome = (tomador.get("nome") or "").strip()
        if not doc_digits or not nome or doc_digits in seen:
            continue
        seen[doc_digits] = {
            "documento": doc_digits,
            "nome": nome,
            "email": tomador.get("email") or "",
            "telefone": tomador.get("telefone") or "",
        }
    return list(seen.values())


def _manual_nfse_payload_from_form(form, emitter: FiscalEmitter) -> dict:
    clinic = emitter.clinic
    service_defaults = _manual_nfse_service_defaults(clinic)
    tomador_nome = (form.get("tomador_nome") or "").strip()
    tomador_documento = _only_digits(form.get("tomador_documento"))
    if not tomador_nome:
        raise ValueError("Informe o nome da clinica tomadora.")
    if len(tomador_documento) not in {11, 14}:
        raise ValueError("Informe um CPF/CNPJ valido para o tomador.")

    raw_value = (form.get("valor_total") or "").strip()
    if "," in raw_value:
        raw_value = raw_value.replace(".", "").replace(",", ".")
    try:
        valor_total = Decimal(raw_value)
    except (InvalidOperation, ValueError):
        raise ValueError("Informe um valor valido para a NFS-e.") from None
    if valor_total <= 0:
        raise ValueError("O valor da NFS-e deve ser maior que zero.")

    data_competencia = (form.get("data_competencia") or date.today().isoformat()).strip()
    try:
        datetime.strptime(data_competencia, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Informe uma data de competencia valida.") from None

    codigo_servico = (
        form.get("codigo_servico")
        or get_clinica_field(clinic, "codigo_servico", "")
        or service_defaults.get("codigo_servico")
        or ""
    ).strip()
    if not codigo_servico:
        raise ValueError("Informe o codigo de servico liberado para a NFS-e.")

    aliquota_iss = (
        form.get("aliquota_iss")
        or get_clinica_field(clinic, "aliquota_iss", "")
        or ""
    )
    codigo_tributacao_municipal = (
        form.get("codigo_tributacao_municipal")
        or service_defaults.get("codigo_tributacao_municipal")
        or ""
    ).strip()
    codigo_nbs = (
        form.get("codigo_nbs")
        or service_defaults.get("codigo_nbs")
        or ""
    ).strip()
    descricao = (
        form.get("descricao")
        or service_defaults.get("descricao")
        or "Atendimento veterinario"
    ).strip()
    municipio_nfse = get_clinica_field(clinic, "municipio_nfse", "") or ""
    municipio_key = _normalize_municipio(municipio_nfse) if municipio_nfse else ""
    municipio_ibge = emitter.municipio_ibge or NFSE_NACIONAL_MUNICIPIO_IBGE_BY_KEY.get(municipio_key)
    is_nacional = municipio_key in NFSE_NACIONAL_MUNICIPIO_IBGE_BY_KEY or municipio_ibge in NFSE_NACIONAL_MUNICIPIO_IBGE

    payload = {
        "provider": "nfse_nacional" if is_nacional else None,
        "municipio_nfse": municipio_nfse,
        "municipio_ibge": municipio_ibge,
        "data_competencia": data_competencia,
        "valor_total": str(valor_total),
        "codigo_servico": codigo_servico,
        "aliquota_iss": str(aliquota_iss) if aliquota_iss not in (None, "") else None,
        "prestador": {
            "cnpj": emitter.cnpj,
            "im": emitter.inscricao_municipal,
            "nome": emitter.razao_social,
            "regime_tributario": emitter.regime_tributario or get_clinica_field(clinic, "regime_tributario", ""),
            "endereco": emitter.endereco_json or {},
        },
        "tomador": {
            "cpf_cnpj": tomador_documento,
            "nome": tomador_nome,
            "email": (form.get("tomador_email") or "").strip() or None,
            "telefone": (form.get("tomador_telefone") or "").strip() or None,
        },
        "servico": {
            "item_lista": codigo_servico,
            "cTribNac": codigo_servico,
            "cTribMun": codigo_tributacao_municipal or None,
            "cNBS": codigo_nbs or None,
            "descricao": descricao,
            "valor": str(valor_total),
            "aliquota_iss": str(aliquota_iss) if aliquota_iss not in (None, "") else None,
        },
        "rps": {
            "serie": (form.get("serie") or "1").strip() or "1",
        },
    }
    return payload


def _emitter_has_active_certificate(emitter: FiscalEmitter | None) -> bool:
    if not emitter:
        return False
    certificate = (
        FiscalCertificate.query
        .filter_by(emitter_id=emitter.id)
        .order_by(FiscalCertificate.created_at.desc())
        .first()
    )
    if not certificate:
        return False
    if not certificate.valid_to:
        return True
    valid_to = certificate.valid_to
    if valid_to.tzinfo is None:
        valid_to = valid_to.replace(tzinfo=timezone.utc)
    return valid_to >= datetime.now(timezone.utc)





@bp.route("/fiscal/settings", methods=["GET", "POST"])
@login_required
def fiscal_settings():
    clinic_id = current_user_clinic_id()
    if not clinic_id:
        abort(403)

    emitter = FiscalEmitter.query.filter_by(clinic_id=clinic_id).first()

    if request.method == "POST":
        cnpj = request.form.get("cnpj", "").strip()
        uf = _normalize_uf(request.form.get("uf"))
        if cnpj and not _validate_cnpj_format(cnpj):
            flash("Informe um CNPJ válido com 14 dígitos.", "warning")
            return render_template(
                "fiscal_settings.html",
                emitter=emitter,
                incomplete=True,
                uf_codes=sorted(FISCAL_UF_CODES),
            )
        if uf and uf not in FISCAL_UF_CODES:
            flash("Informe uma UF válida.", "warning")
            return render_template(
                "fiscal_settings.html",
                emitter=emitter,
                incomplete=True,
                uf_codes=sorted(FISCAL_UF_CODES),
            )

        data = {
            "cnpj": cnpj,
            "razao_social": request.form.get("razao_social", "").strip(),
            "nome_fantasia": request.form.get("nome_fantasia", "").strip(),
            "inscricao_municipal": request.form.get("inscricao_municipal", "").strip(),
            "inscricao_estadual": request.form.get("inscricao_estadual", "").strip(),
            "municipio_ibge": request.form.get("municipio_ibge", "").strip(),
            "uf": uf,
            "regime_tributario": request.form.get("regime_tributario", "").strip(),
        }

        if emitter is None:
            emitter = FiscalEmitter(clinic_id=clinic_id, **data)
            db.session.add(emitter)
        else:
            for key, value in data.items():
                setattr(emitter, key, value)

        db.session.commit()
        flash("Configuração fiscal salva com sucesso.", "success")

    incomplete = any(
        not getattr(emitter, field)
        for field in ("cnpj", "razao_social", "municipio_ibge", "uf", "regime_tributario")
    ) if emitter else True

    return render_template(
        "fiscal_settings.html",
        emitter=emitter,
        incomplete=incomplete,
        uf_codes=sorted(FISCAL_UF_CODES),
    )


@bp.route("/fiscal/certificate", methods=["GET", "POST"])
@login_required
def fiscal_certificate_upload():
    clinic_id = current_user_clinic_id()
    if not clinic_id:
        abort(403)

    emitter = FiscalEmitter.query.filter_by(clinic_id=clinic_id).first()
    if emitter is None or not emitter.cnpj:
        flash("Cadastre o emissor fiscal antes de enviar o certificado.", "warning")
        return redirect(url_for("fiscal_settings"))

    if request.method == "POST":
        pfx_file = request.files.get("pfx_file")
        password = request.form.get("pfx_password") or ""

        if not pfx_file or pfx_file.filename == "":
            flash("Selecione um arquivo .pfx.", "warning")
            return render_template(
                "fiscal_certificate_upload.html",
                emitter=emitter,
                certificates=[],
            )

        try:
            pfx_bytes = pfx_file.read()
            if not pfx_bytes:
                raise ValueError("Arquivo PFX vazio.")
            info = parse_pfx(pfx_bytes, password)
        except Exception as exc:
            flash(f"Não foi possível ler o certificado: {exc}", "danger")
            return render_template(
                "fiscal_certificate_upload.html",
                emitter=emitter,
                certificates=[],
            )

        emitter_cnpj = _normalize_cnpj(emitter.cnpj)
        subject_cnpj = info.get("subject_cnpj") or ""
        if not subject_cnpj:
            flash("Não foi possível identificar o CNPJ do certificado.", "danger")
            return render_template(
                "fiscal_certificate_upload.html",
                emitter=emitter,
                certificates=[],
            )
        if subject_cnpj != emitter_cnpj:
            flash("O CNPJ do certificado não corresponde ao emissor fiscal.", "danger")
            return render_template(
                "fiscal_certificate_upload.html",
                emitter=emitter,
                certificates=[],
            )

        certificate = FiscalCertificate(
            emitter_id=emitter.id,
            pfx_encrypted=encrypt_bytes(pfx_bytes),
            pfx_password_encrypted=encrypt_text(password),
            fingerprint_sha256=info["fingerprint_sha256"],
            valid_from=info["valid_from"],
            valid_to=info["valid_to"],
            subject_cnpj=subject_cnpj,
        )
        db.session.add(certificate)
        db.session.commit()
        flash("Certificado fiscal enviado com sucesso.", "success")
        return redirect(url_for("fiscal_certificate_upload"))

    certificates = (
        FiscalCertificate.query
        .filter_by(emitter_id=emitter.id)
        .order_by(FiscalCertificate.created_at.desc())
        .all()
    )

    return render_template(
        "fiscal_certificate_upload.html",
        emitter=emitter,
        certificates=certificates,
    )


@bp.route("/fiscal/documents", methods=["GET"])
@login_required
def fiscal_documents():
    clinic_id = current_user_clinic_id()
    if not clinic_id:
        abort(403)

    query = FiscalDocument.query.filter_by(clinic_id=clinic_id)
    doc_type = request.args.get("doc_type")
    status = request.args.get("status")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    if doc_type:
        try:
            query = query.filter(
                FiscalDocument.doc_type == FiscalDocumentType[doc_type.upper()]
            )
        except KeyError:
            flash("Tipo de documento inválido.", "warning")

    if status:
        try:
            query = query.filter(
                FiscalDocument.status == FiscalDocumentStatus[status.upper()]
            )
        except KeyError:
            flash("Status fiscal inválido.", "warning")

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(FiscalDocument.created_at >= start_dt)
        except ValueError:
            flash("Data inicial inválida.", "warning")
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(FiscalDocument.created_at < end_dt)
        except ValueError:
            flash("Data final inválida.", "warning")

    documents = query.order_by(FiscalDocument.created_at.desc()).all()
    emitter = FiscalEmitter.query.filter_by(clinic_id=clinic_id).first()
    clinic = emitter.clinic if emitter else None
    service_defaults = _manual_nfse_service_defaults(clinic)
    certificate_ready = _emitter_has_active_certificate(emitter)
    manual_defaults = {
        "descricao": service_defaults.get("descricao", "Atendimento veterinario"),
        "data_competencia": date.today().isoformat(),
        "codigo_servico": (
            get_clinica_field(clinic, "codigo_servico", "") if clinic else ""
        ) or service_defaults.get("codigo_servico", ""),
        "aliquota_iss": get_clinica_field(clinic, "aliquota_iss", "") if clinic else "",
        "codigo_tributacao_municipal": service_defaults.get("codigo_tributacao_municipal", ""),
        "codigo_nbs": service_defaults.get("codigo_nbs", ""),
    }

    return render_template(
        "fiscal_documents.html",
        documents=documents,
        emitter=emitter,
        certificate_ready=certificate_ready,
        recent_tomadores=_recent_nfse_tomadores(clinic_id),
        manual_defaults=manual_defaults,
        doc_type=doc_type or "",
        status=status or "",
        start_date=start_date or "",
        end_date=end_date or "",
        doc_types=[doc_type.value for doc_type in FiscalDocumentType],
        status_options=[
            status.value
            for status in FiscalDocumentStatus
            if status != FiscalDocumentStatus.SENDING
        ],
    )


@bp.route("/fiscal/nfse/manual", methods=["POST"])
@login_required
def fiscal_nfse_manual():
    clinic_id = current_user_clinic_id()
    if not clinic_id:
        abort(403)

    emitter = FiscalEmitter.query.filter_by(clinic_id=clinic_id).first()
    if not emitter:
        flash("Cadastre o emissor fiscal antes de emitir NFS-e.", "warning")
        return redirect(url_for("fiscal_settings"))

    try:
        payload = _manual_nfse_payload_from_form(request.form, emitter)
        certificate_ready = _emitter_has_active_certificate(emitter)
        document = create_manual_nfse_document(
            emitter.id,
            payload,
            initial_status=(
                FiscalDocumentStatus.QUEUED
                if certificate_ready
                else FiscalDocumentStatus.DRAFT
            ),
        )
        if not certificate_ready:
            flash("NFS-e criada como rascunho. Envie o certificado fiscal A1 antes de emitir.", "warning")
            return redirect(url_for("fiscal_document_detail", document_id=document.id))
        try:
            queue_emit_nfse(document.id, clinic_id=clinic_id)
        except Exception:  # noqa: BLE001
            current_app.logger.exception("Falha ao enviar NFS-e manual para a fila.")
            flash("NFS-e criada, mas nao foi possivel iniciar a fila agora. Tente reprocessar em instantes.", "warning")
            return redirect(url_for("fiscal_document_detail", document_id=document.id))
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("fiscal_documents"))

    flash("NFS-e manual criada e enviada para emissao.", "success")
    return redirect(url_for("fiscal_document_detail", document_id=document.id))


@bp.route("/fiscal/documents/<int:document_id>", methods=["GET"])
@login_required
def fiscal_document_detail(document_id: int):
    clinic_id = current_user_clinic_id()
    if not clinic_id:
        abort(403)

    document = FiscalDocument.query.filter_by(id=document_id, clinic_id=clinic_id).first_or_404()
    appointment = None
    if document.related_type == "appointment" and document.related_id:
        from models import Appointment

        appointment = Appointment.query.filter_by(
            id=document.related_id,
            clinica_id=clinic_id,
        ).first()
    events = (
        FiscalEvent.query
        .filter_by(document_id=document.id)
        .order_by(FiscalEvent.created_at.asc())
        .all()
    )
    payload_pretty = ""
    if document.payload_json:
        payload_pretty = json.dumps(document.payload_json, ensure_ascii=False, indent=2)

    return render_template(
        "fiscal_document_detail.html",
        document=document,
        appointment=appointment,
        events=events,
        payload_pretty=payload_pretty,
    )


@bp.route("/fiscal/documents/<int:document_id>/emit", methods=["POST"])
@login_required
def fiscal_document_emit(document_id: int):
    clinic_id = current_user_clinic_id()
    if not clinic_id:
        abort(403)

    document = FiscalDocument.query.filter_by(id=document_id, clinic_id=clinic_id).first_or_404()
    if not _emitter_has_active_certificate(document.emitter):
        flash("Envie o certificado fiscal A1 antes de emitir esta NFS-e.", "warning")
        return redirect(url_for("fiscal_document_detail", document_id=document.id))
    try:
        queue_emit_nfse(document.id, clinic_id=clinic_id)
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Falha ao enviar NFS-e para a fila.")
        flash("Nao foi possivel iniciar a emissao agora. Tente novamente em instantes.", "warning")
        return redirect(url_for("fiscal_document_detail", document_id=document.id))
    flash("NFS-e enviada para emissao.", "success")
    return redirect(url_for("fiscal_document_detail", document_id=document.id))


@bp.route("/fiscal/documents/<int:document_id>/status", methods=["GET"])
@login_required
def fiscal_document_status(document_id: int):
    clinic_id = current_user_clinic_id()
    if not clinic_id:
        abort(403)

    document = FiscalDocument.query.filter_by(id=document_id, clinic_id=clinic_id).first_or_404()
    return jsonify(
        {
            "id": document.id,
            "status": document.status.value if document.status else document.status,
            "access_key": document.access_key,
            "nfse_number": document.nfse_number,
            "verification_code": document.verification_code,
            "error_message": document.error_message,
        }
    )


@bp.route("/fiscal/documents/<int:document_id>/cancel", methods=["POST"])
@login_required
def fiscal_document_cancel(document_id: int):
    clinic_id = current_user_clinic_id()
    if not clinic_id:
        abort(403)

    document = FiscalDocument.query.filter_by(id=document_id, clinic_id=clinic_id).first_or_404()
    try:
        cancel_nfse_document(document.id)
        flash("Cancelamento solicitado.", "success")
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Erro ao cancelar NFS-e", exc_info=exc)
        flash("Erro ao solicitar cancelamento.", "danger")
    return redirect(url_for("fiscal_document_detail", document_id=document.id))

