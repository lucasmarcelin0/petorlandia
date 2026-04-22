import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db  # noqa: E402
from models import (  # noqa: E402
    AccountingAccount,
    BankStatementTransaction,
    Clinica,
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalDocumentType,
    FiscalEmitter,
    Orcamento,
    OrcamentoItem,
    User,
)
from services.finance import (  # noqa: E402
    build_cash_flow_report,
    build_dre_report,
    export_accountant_xlsx,
    import_bank_statement,
    sync_receivable_from_nfse,
)


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    yield flask_app


def _clinic():
    clinic = Clinica(nome="Clinica Fase 3", aliquota_iss=Decimal("5.00"))
    db.session.add(clinic)
    db.session.flush()
    return clinic


def test_authorized_nfse_creates_receivable_with_net_amount(app):
    with app.app_context():
        clinic = _clinic()
        emitter = FiscalEmitter(
            clinic_id=clinic.id,
            cnpj="12345678000100",
            razao_social="Clinica Fase 3 Ltda",
        )
        db.session.add(emitter)
        db.session.flush()

        document = FiscalDocument(
            emitter_id=emitter.id,
            clinic_id=clinic.id,
            doc_type=FiscalDocumentType.NFSE,
            status=FiscalDocumentStatus.AUTHORIZED,
            number=10,
            nfse_number="NF10",
            tutor_name="Tutor",
            payload_json={"valor_total": "1000.00"},
            authorized_at=datetime(2026, 4, 20, 10, 0),
        )
        db.session.add(document)
        db.session.commit()

        account = sync_receivable_from_nfse(document)

        assert account.kind == "receivable"
        assert account.status == "open"
        assert account.gross_amount == Decimal("1000.00")
        assert account.tax_amount == Decimal("50.00")
        assert account.net_amount == Decimal("950.00")
        assert account.due_date == date(2026, 5, 20)


def test_dre_and_cash_flow_include_classified_revenue_and_accounts(app):
    with app.app_context():
        clinic = _clinic()
        orcamento = Orcamento(
            clinica_id=clinic.id,
            descricao="Consulta abril",
            created_at=datetime(2026, 4, 5, 9, 0),
        )
        db.session.add(orcamento)
        db.session.flush()
        db.session.add(
            OrcamentoItem(
                orcamento_id=orcamento.id,
                clinica_id=clinic.id,
                descricao="Consulta",
                valor=Decimal("300.00"),
            )
        )
        db.session.add(
            AccountingAccount(
                clinic_id=clinic.id,
                kind="receivable",
                status="open",
                description="Receber plano",
                gross_amount=Decimal("200.00"),
                tax_amount=Decimal("0.00"),
                net_amount=Decimal("200.00"),
                due_date=date.today() + timedelta(days=15),
            )
        )
        db.session.commit()

        dre = build_dre_report(clinic.id, date(2026, 4, 1))
        cash = build_cash_flow_report(clinic.id, date(2026, 4, 1))

        assert dre["totals"]["receita_bruta"] == Decimal("300.00")
        assert dre["totals"]["impostos"] == Decimal("33.00")
        assert cash["realizado"]["entradas"] == Decimal("300.00")
        assert cash["projecoes"]["30"]["entradas"] == Decimal("200.00")


def test_ofx_import_matches_open_receivable(app):
    with app.app_context():
        clinic = _clinic()
        account = AccountingAccount(
            clinic_id=clinic.id,
            kind="receivable",
            status="open",
            description="NFS-e NF11",
            gross_amount=Decimal("950.00"),
            tax_amount=Decimal("0.00"),
            net_amount=Decimal("950.00"),
            due_date=date(2026, 4, 22),
        )
        db.session.add(account)
        db.session.commit()

        result = import_bank_statement(
            clinic.id,
            """
            <OFX><BANKTRANLIST>
              <STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260423000000<TRNAMT>950.00<FITID>abc-1<MEMO>Pix Tutor
            </BANKTRANLIST></OFX>
            """,
        )

        assert result["matched"] == 1
        assert AccountingAccount.query.get(account.id).status == "paid"
        assert BankStatementTransaction.query.count() == 1


def test_accountant_xlsx_export_is_valid_zip(app):
    with app.app_context():
        clinic = _clinic()
        content = export_accountant_xlsx(clinic.id, date(2026, 4, 1))

        assert content.startswith(b"PK")
        assert b"xl/workbook.xml" in content
