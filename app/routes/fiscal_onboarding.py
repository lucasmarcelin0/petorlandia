"""Wizard de onboarding fiscal."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from extensions import db
from helpers import has_veterinarian_profile
from models import (
    Clinica,
    FiscalCertificate,
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalDocumentType,
    FiscalEmitter,
    FiscalEvent,
)
from security.crypto import encrypt_bytes, encrypt_text
from services.fiscal.certificate import parse_pfx


FISCAL_UF_CODES = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
    "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}

STEP_TITLES = {
    1: "Dados do emissor",
    2: "Certificado A1",
    3: "Testes (Betha + SEFAZ)",
    4: "Aceite",
}


def _current_user_clinic_id():
    if not current_user.is_authenticated:
        return None
    if has_veterinarian_profile(current_user):
        return getattr(current_user.veterinario, "clinica_id", None)
    return current_user.clinica_id


def _normalize_cnpj(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _validate_cnpj_format(value: str | None) -> bool:
    digits = _normalize_cnpj(value)
    return len(digits) == 14


def _normalize_uf(value: str | None) -> str:
    return (value or "").strip().upper()


def _emitter_is_complete(emitter: FiscalEmitter | None) -> bool:
    if not emitter:
        return False
    required_fields = ("cnpj", "razao_social", "municipio_ibge", "uf", "regime_tributario")
    return all(getattr(emitter, field) for field in required_fields)


def _get_latest_onboarding_document(clinic_id: int) -> FiscalDocument | None:
    return (
        FiscalDocument.query
        .filter_by(clinic_id=clinic_id, related_type="onboarding_test")
        .order_by(FiscalDocument.created_at.desc())
        .first()
    )


def _wizard_steps(step1_complete: bool, step2_complete: bool, step3_complete: bool, clinic_ready: bool):
    return [
        {"number": 1, "title": STEP_TITLES[1], "complete": step1_complete},
        {"number": 2, "title": STEP_TITLES[2], "complete": step2_complete},
        {"number": 3, "title": STEP_TITLES[3], "complete": step3_complete},
        {"number": 4, "title": STEP_TITLES[4], "complete": clinic_ready},
    ]


@login_required
def fiscal_onboarding_start():
    return redirect(url_for("fiscal_onboarding_step", step=1))


@login_required
def fiscal_onboarding_step(step: int):
    if step not in STEP_TITLES:
        abort(404)

    clinic_id = _current_user_clinic_id()
    if not clinic_id:
        abort(403)

    clinic = Clinica.query.filter_by(id=clinic_id).first_or_404()
    emitter = FiscalEmitter.query.filter_by(clinic_id=clinic_id).first()
    certificates = []
    if emitter:
        certificates = (
            FiscalCertificate.query
            .filter_by(emitter_id=emitter.id)
            .order_by(FiscalCertificate.created_at.desc())
            .all()
        )

    comm_tested_at = session.get("fiscal_onboarding_comm_at")
    emission_doc = _get_latest_onboarding_document(clinic_id)

    step1_complete = _emitter_is_complete(emitter)
    step2_complete = bool(certificates)
    step3_complete = bool(comm_tested_at) and emission_doc is not None
    wizard_steps = _wizard_steps(step1_complete, step2_complete, step3_complete, clinic.fiscal_ready)

    if request.method == "POST":
        if step == 1:
            cnpj = request.form.get("cnpj", "").strip()
            uf = _normalize_uf(request.form.get("uf"))
            if cnpj and not _validate_cnpj_format(cnpj):
                flash("Informe um CNPJ válido com 14 dígitos.", "warning")
                return render_template(
                    "fiscal_onboarding_step1.html",
                    emitter=emitter,
                    uf_codes=sorted(FISCAL_UF_CODES),
                    wizard_steps=wizard_steps,
                    current_step=step,
                    incomplete=True,
                )
            if uf and uf not in FISCAL_UF_CODES:
                flash("Informe uma UF válida.", "warning")
                return render_template(
                    "fiscal_onboarding_step1.html",
                    emitter=emitter,
                    uf_codes=sorted(FISCAL_UF_CODES),
                    wizard_steps=wizard_steps,
                    current_step=step,
                    incomplete=True,
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
            flash("Dados do emissor salvos com sucesso.", "success")
            return redirect(url_for("fiscal_onboarding_step", step=2))

        if step == 2:
            if emitter is None or not emitter.cnpj:
                flash("Cadastre os dados do emissor antes de enviar o certificado.", "warning")
                return redirect(url_for("fiscal_onboarding_step", step=1))

            pfx_file = request.files.get("pfx_file")
            password = request.form.get("pfx_password") or ""

            if not pfx_file or pfx_file.filename == "":
                flash("Selecione um arquivo .pfx.", "warning")
                return render_template(
                    "fiscal_onboarding_step2.html",
                    emitter=emitter,
                    certificates=certificates,
                    wizard_steps=wizard_steps,
                    current_step=step,
                )

            try:
                pfx_bytes = pfx_file.read()
                if not pfx_bytes:
                    raise ValueError("Arquivo PFX vazio.")
                info = parse_pfx(pfx_bytes, password)
            except Exception as exc:  # noqa: BLE001
                flash(f"Não foi possível ler o certificado: {exc}", "danger")
                return render_template(
                    "fiscal_onboarding_step2.html",
                    emitter=emitter,
                    certificates=certificates,
                    wizard_steps=wizard_steps,
                    current_step=step,
                )

            emitter_cnpj = _normalize_cnpj(emitter.cnpj)
            subject_cnpj = info.get("subject_cnpj") or ""
            if not subject_cnpj:
                flash("Não foi possível identificar o CNPJ do certificado.", "danger")
                return render_template(
                    "fiscal_onboarding_step2.html",
                    emitter=emitter,
                    certificates=certificates,
                    wizard_steps=wizard_steps,
                    current_step=step,
                )
            if subject_cnpj != emitter_cnpj:
                flash("O CNPJ do certificado não corresponde ao emissor fiscal.", "danger")
                return render_template(
                    "fiscal_onboarding_step2.html",
                    emitter=emitter,
                    certificates=certificates,
                    wizard_steps=wizard_steps,
                    current_step=step,
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
            return redirect(url_for("fiscal_onboarding_step", step=3))

        if step == 3:
            action = request.form.get("action")
            if action == "communication_test":
                session["fiscal_onboarding_comm_at"] = datetime.now(timezone.utc).isoformat()
                session.modified = True
                flash("Teste de comunicação marcado como concluído.", "success")
                return redirect(url_for("fiscal_onboarding_step", step=3))

            if action == "emission_test":
                if emitter is None or not certificates:
                    flash("Envie o certificado antes de testar a emissão.", "warning")
                    return redirect(url_for("fiscal_onboarding_step", step=2))

                payload = {
                    "source": "fiscal_onboarding",
                    "dummy": True,
                    "created_by": current_user.id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                document = FiscalDocument(
                    emitter_id=emitter.id,
                    clinic_id=clinic_id,
                    doc_type=FiscalDocumentType.NFSE,
                    status=FiscalDocumentStatus.DRAFT,
                    series="TESTE",
                    payload_json=payload,
                    related_type="onboarding_test",
                )
                db.session.add(document)
                db.session.flush()

                event = FiscalEvent(
                    document_id=document.id,
                    event_type="EMISSION_TEST",
                    status="CREATED",
                    error_message="Documento dummy criado para onboarding.",
                )
                db.session.add(event)
                db.session.commit()

                flash("Documento dummy criado para teste de emissão.", "success")
                return redirect(url_for("fiscal_onboarding_step", step=3))

        if step == 4:
            if not (step1_complete and step2_complete and step3_complete):
                flash("Conclua os passos anteriores antes de aceitar.", "warning")
                return redirect(url_for("fiscal_onboarding_step", step=step))

            clinic.fiscal_ready = True
            db.session.commit()
            flash("Wizard fiscal concluído! Sua clínica está pronta para emissão.", "success")
            return redirect(url_for("fiscal_onboarding_step", step=4))

    if step == 1:
        return render_template(
            "fiscal_onboarding_step1.html",
            emitter=emitter,
            uf_codes=sorted(FISCAL_UF_CODES),
            wizard_steps=wizard_steps,
            current_step=step,
            incomplete=not step1_complete,
        )

    if step == 2:
        return render_template(
            "fiscal_onboarding_step2.html",
            emitter=emitter,
            certificates=certificates,
            wizard_steps=wizard_steps,
            current_step=step,
        )

    if step == 3:
        return render_template(
            "fiscal_onboarding_step3.html",
            emitter=emitter,
            certificates=certificates,
            comm_tested_at=comm_tested_at,
            emission_doc=emission_doc,
            wizard_steps=wizard_steps,
            current_step=step,
        )

    return render_template(
        "fiscal_onboarding_step4.html",
        clinic=clinic,
        emitter=emitter,
        comm_tested_at=comm_tested_at,
        emission_doc=emission_doc,
        wizard_steps=wizard_steps,
        current_step=step,
        step1_complete=step1_complete,
        step2_complete=step2_complete,
        step3_complete=step3_complete,
    )
