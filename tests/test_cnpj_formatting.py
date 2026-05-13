from app import format_cnpj as template_format_cnpj
from extensions import db
from models import Clinica, FiscalCertificate, FiscalEmitter


def test_template_filter_formats_plain_cnpj():
    assert template_format_cnpj("62126629000130") == "62.126.629/0001-30"


def test_models_normalize_cnpj_storage(app):
    with app.app_context():
        clinic = Clinica(nome="Clinica Teste", cnpj="62126629000130")
        db.session.add(clinic)
        db.session.flush()

        emitter = FiscalEmitter(
            clinic_id=clinic.id,
            cnpj="62126629000130",
            razao_social="Clinica Teste LTDA",
        )
        db.session.add(emitter)
        db.session.flush()

        certificate = FiscalCertificate(
            emitter_id=emitter.id,
            pfx_encrypted=b"fake-pfx",
            pfx_password_encrypted="fake-password",
            fingerprint_sha256="a" * 64,
            subject_cnpj="62126629000130",
        )
        db.session.add(certificate)
        db.session.flush()

        assert clinic.cnpj == "62.126.629/0001-30"
        assert emitter.cnpj == "62.126.629/0001-30"
        assert certificate.subject_cnpj == "62126629000130"
