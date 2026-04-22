import json
from decimal import Decimal

import pytest

from extensions import db
from models import (
    Clinica,
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalDocumentType,
    FiscalEmitter,
    NfseIssue,
    NfseXml,
)
from services.fiscal.nfse_service import FiscalXmlParseError, _extract_xml_value, _redact_xml
from services.nfse_service import NfseService, _compact_xml


def test_legacy_nfse_adapter_delega_para_fiscal_document_sem_sucesso_fake(app):
    with app.app_context():
        clinic = Clinica(
            nome="Clinica Fase 2",
            cnpj="12345678000100",
            inscricao_municipal="12345",
            municipio_nfse="Orlandia",
        )
        db.session.add(clinic)
        db.session.flush()
        emitter = FiscalEmitter(
            clinic_id=clinic.id,
            cnpj="12345678000100",
            razao_social="Clinica Fase 2 Ltda",
            inscricao_municipal="12345",
            municipio_ibge="3534303",
        )
        db.session.add(emitter)
        issue = NfseIssue(
            clinica_id=clinic.id,
            status="fila",
            serie="A1",
            valor_total=Decimal("150.00"),
            tomador=json.dumps(
                {
                    "nome": "Tutor Teste",
                    "cpf_cnpj": "12345678901",
                    "animal_nome": "Paciente",
                }
            ),
            prestador=json.dumps({"cnpj": clinic.cnpj, "im": clinic.inscricao_municipal}),
        )
        db.session.add(issue)
        db.session.commit()

        result = NfseService().emitir_nfse(issue, {}, "Orlandia")

        document = FiscalDocument.query.filter_by(
            clinic_id=clinic.id,
            doc_type=FiscalDocumentType.NFSE,
            source_type="NFSE_ISSUE",
            source_id=issue.id,
        ).one()
        assert result.success is False
        assert result.xml_request is None
        assert result.xml_response is None
        assert document.status == FiscalDocumentStatus.FAILED
        assert document.error_code == "ValueError"
        assert document.related_type == "nfse_issue"
        assert document.related_id == issue.id
        assert issue.status == "erro"
        assert issue.rps == str(document.number)
        assert NfseXml.query.count() == 0


def test_extract_xml_value_usa_parser_seguro_e_namespace(app):
    xml = '<ns:Resposta xmlns:ns="urn:test"><ns:Protocolo>abc-123</ns:Protocolo></ns:Resposta>'

    with app.app_context():
        assert _extract_xml_value(xml, "Protocolo") == "abc-123"
        assert _extract_xml_value(xml, "Numero") is None

        with pytest.raises(FiscalXmlParseError):
            _extract_xml_value("<Resposta><Protocolo>", "Protocolo")

        with pytest.raises(FiscalXmlParseError):
            _extract_xml_value(
                '<!DOCTYPE r [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
                "<r><Protocolo>&xxe;</Protocolo></r>",
                "Protocolo",
            )


def test_xml_redaction_mascara_conteudo_de_tags_e_digitos_sensiveis():
    xml = (
        "<Root><Tomador><Cpf>12345678901</Cpf><Cnpj>12345678000100</Cnpj>"
        "<Descricao>CPF solto 10987654321 e CNPJ solto 00998877000166</Descricao>"
        "</Tomador></Root>"
    )

    redacted = _redact_xml(xml)
    compact = _compact_xml(xml)

    assert "12345678901" not in redacted
    assert "12345678000100" not in redacted
    assert "10987654321" not in compact
    assert "00998877000166" not in compact
    assert "<Cpf>***</Cpf>" in redacted
