"""Fluxo de emissão NF-e: lote síncrono, chave estável e cancelamento.

O cliente da SEFAZ é trocado por um dublê; o que se testa é como o serviço
monta o lote, interpreta o retorno e grava o documento.
"""
from __future__ import annotations

import datetime
import hashlib

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from extensions import db
from models import (
    FiscalCertificate,
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalDocumentType,
    FiscalEmitter,
    FiscalEvent,
)
from providers.nfe.sefaz_sp.client import SefazSoapResponse
from security.crypto import clear_crypto_cache, encrypt_bytes, encrypt_text
from services.fiscal import nfe_service


NFE = "http://www.portalfiscal.inf.br/nfe"


@pytest.fixture()
def fiscal_env(app, monkeypatch):
    monkeypatch.setenv("FISCAL_MASTER_KEY", "chave-mestra-de-teste-nfe")
    monkeypatch.setenv("NFE_ENV", "homolog")
    clear_crypto_cache()

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CLINICA TESTE:12345678000195")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(7).not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=60)).sign(key, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(
        b"a1", key, cert, None, serialization.BestAvailableEncryption(b"senha")
    )

    emitter = FiscalEmitter(
        clinic_id=1,
        cnpj="12.345.678/0001-95",
        razao_social="Clinica Teste Ltda",
        uf="SP",
        municipio_ibge="3534302",
        regime_tributario="Simples Nacional",
        endereco_json={"logradouro": "Rua Oito", "numero": "100", "bairro": "Centro", "cidade": "Orlandia", "cep": "14620000"},
    )
    db.session.add(emitter)
    db.session.flush()
    db.session.add(
        FiscalCertificate(
            emitter_id=emitter.id,
            pfx_encrypted=encrypt_bytes(pfx),
            pfx_password_encrypted=encrypt_text("senha"),
            fingerprint_sha256=hashlib.sha256(pfx).hexdigest(),
        )
    )
    document = FiscalDocument(
        emitter_id=emitter.id,
        clinic_id=1,
        doc_type=FiscalDocumentType.NFE,
        status=FiscalDocumentStatus.QUEUED,
        series="1",
        number=15,
        payload_json={"items": [{"name": "Racao 1kg", "quantity": 2, "unit_price": 30, "ncm": "23091000"}]},
    )
    db.session.add(document)
    db.session.commit()
    return {"emitter": emitter, "document": document}


class FakeClient:
    def __init__(self, autorizacao=None, consulta=None, evento=None):
        self._autorizacao = list(autorizacao or [])
        self._consulta = consulta
        self._evento = evento
        self.lotes: list[str] = []
        self.wsdl_config = type("Cfg", (), {"autorizacao": "https://homologacao/ws/nfeautorizacao4.asmx"})()

    def autorizacao(self, xml):
        self.lotes.append(xml)
        return self._autorizacao.pop(0)

    def ret_autorizacao(self, xml):  # pragma: no cover - não usado nos cenários síncronos
        raise AssertionError("não deveria consultar recibo")

    def consulta_protocolo(self, xml):
        return self._consulta

    def evento_cancelamento(self, chave, xml):
        return self._evento


def _ok(inner: str) -> SefazSoapResponse:
    return SefazSoapResponse(True, inner, "<req/>", f"<env>{inner}</env>")


def _prot(chave: str, c_stat: str = "100", motivo: str = "Autorizado o uso da NF-e") -> str:
    return (
        f'<protNFe xmlns="{NFE}" versao="4.00"><infProt><tpAmb>2</tpAmb><chNFe>{chave}</chNFe>'
        f"<nProt>135260000000042</nProt><cStat>{c_stat}</cStat><xMotivo>{motivo}</xMotivo></infProt></protNFe>"
    )


def _ret_sincrono(chave: str, c_stat: str = "100", motivo: str = "Autorizado o uso da NF-e") -> str:
    prot = _prot(chave, c_stat, motivo).replace(f' xmlns="{NFE}"', "")
    return (
        f'<retEnviNFe xmlns="{NFE}" versao="4.00"><cStat>104</cStat><xMotivo>Lote processado</xMotivo>'
        f"{prot}</retEnviNFe>"
    )


def _chave_do_lote(lote: str) -> str:
    root = etree.fromstring(lote.encode("utf-8"))
    return root.find(f".//{{{NFE}}}infNFe").get("Id")[3:]


def test_emissao_sincrona_autorizada_grava_nfeproc(fiscal_env, monkeypatch):
    document = fiscal_env["document"]
    fake = FakeClient()

    def responder(xml):
        fake.lotes.append(xml)
        return _ok(_ret_sincrono(_chave_do_lote(xml)))

    fake.autorizacao = responder
    monkeypatch.setattr(nfe_service, "_build_sefaz_client", lambda certificate, env: fake)

    result = nfe_service.emit_nfe_sync(document.id)

    assert result.status == FiscalDocumentStatus.AUTHORIZED
    assert result.protocol == "135260000000042"
    lote = etree.fromstring(fake.lotes[0].encode("utf-8"))
    assert lote.tag == f"{{{NFE}}}enviNFe"
    assert lote.find(f"{{{NFE}}}indSinc").text == "1"
    chave = _chave_do_lote(fake.lotes[0])
    assert result.access_key == chave and len(chave) == 44
    proc = etree.fromstring(result.xml_authorized.encode("utf-8"))
    assert proc.tag == f"{{{NFE}}}nfeProc"
    assert proc.find(f"{{{NFE}}}NFe") is not None and proc.find(f"{{{NFE}}}protNFe") is not None

    # Simples Nacional: sem base de ICMS no total e PIS/COFINS sem destaque.
    nfe = lote.find(f"{{{NFE}}}NFe")
    assert nfe.find(f".//{{{NFE}}}ICMSTot/{{{NFE}}}vBC").text == "0.00"
    assert nfe.find(f".//{{{NFE}}}PISOutr/{{{NFE}}}CST").text == "99"
    dh_emi = nfe.find(f".//{{{NFE}}}dhEmi").text
    assert "." not in dh_emi and dh_emi[-6:-3] in {"-03", "-02"}
    # AAMM da chave = ano/mês do dhEmi.
    assert chave[2:6] == dh_emi[2:4] + dh_emi[5:7]
    assert chave[35:43] != f"{document.number:08d}", "cNF não pode repetir o número da nota"


def test_falha_de_rede_marca_failed_e_reenvio_repete_a_chave(fiscal_env, monkeypatch):
    document = fiscal_env["document"]
    fake = FakeClient(autorizacao=[SefazSoapResponse(False, None, "<req/>", None, "Read timed out")])
    monkeypatch.setattr(nfe_service, "_build_sefaz_client", lambda certificate, env: fake)

    first = nfe_service.emit_nfe_sync(document.id)
    assert first.status == FiscalDocumentStatus.FAILED
    primeira_chave = first.access_key

    def responder(xml):
        fake.lotes.append(xml)
        return _ok(_ret_sincrono(_chave_do_lote(xml)))

    fake.autorizacao = responder
    second = nfe_service.emit_nfe_sync(document.id)
    assert second.status == FiscalDocumentStatus.AUTHORIZED
    assert second.access_key == primeira_chave
    assert _chave_do_lote(fake.lotes[-1]) == primeira_chave


def test_duplicidade_consulta_a_chave_e_aproveita_autorizacao(fiscal_env, monkeypatch):
    document = fiscal_env["document"]
    fake = FakeClient()

    def responder(xml):
        fake.lotes.append(xml)
        chave = _chave_do_lote(xml)
        fake._consulta = _ok(
            f'<retConsSitNFe xmlns="{NFE}" versao="4.00"><cStat>100</cStat><xMotivo>Autorizado</xMotivo>'
            + _prot(chave).replace(f' xmlns="{NFE}"', "")
            + "</retConsSitNFe>"
        )
        return _ok(
            f'<retEnviNFe xmlns="{NFE}" versao="4.00"><cStat>104</cStat><xMotivo>Lote processado</xMotivo>'
            + _prot(chave, "204", "Duplicidade de NF-e").replace(f' xmlns="{NFE}"', "")
            + "</retEnviNFe>"
        )

    fake.autorizacao = responder
    monkeypatch.setattr(nfe_service, "_build_sefaz_client", lambda certificate, env: fake)

    result = nfe_service.emit_nfe_sync(document.id)
    assert result.status == FiscalDocumentStatus.AUTHORIZED
    assert result.protocol == "135260000000042"


def test_duplicidade_com_consulta_sem_resposta_fica_recuperavel(fiscal_env, monkeypatch):
    """204 + consulta que não responde: FAILED (reprocessável), não REJECTED."""
    document = fiscal_env["document"]
    fake = FakeClient(consulta=SefazSoapResponse(False, None, "<req/>", None, "Read timed out"))

    def responder(xml):
        fake.lotes.append(xml)
        return _ok(
            f'<retEnviNFe xmlns="{NFE}" versao="4.00"><cStat>104</cStat><xMotivo>Lote processado</xMotivo>'
            + _prot(_chave_do_lote(xml), "204", "Duplicidade de NF-e").replace(f' xmlns="{NFE}"', "")
            + "</retEnviNFe>"
        )

    fake.autorizacao = responder
    monkeypatch.setattr(nfe_service, "_build_sefaz_client", lambda certificate, env: fake)

    result = nfe_service.emit_nfe_sync(document.id)
    assert result.status == FiscalDocumentStatus.FAILED
    assert result.error_code == "204"
    assert "sem confirmação" in result.error_message


def test_duplicidade_de_nota_cancelada_nao_vira_autorizada(fiscal_env, monkeypatch):
    document = fiscal_env["document"]
    fake = FakeClient()

    def responder(xml):
        fake.lotes.append(xml)
        chave = _chave_do_lote(xml)
        fake._consulta = _ok(
            f'<retConsSitNFe xmlns="{NFE}" versao="4.00"><cStat>101</cStat><xMotivo>Cancelamento homologado</xMotivo>'
            + _prot(chave).replace(f' xmlns="{NFE}"', "")
            + "</retConsSitNFe>"
        )
        return _ok(
            f'<retEnviNFe xmlns="{NFE}" versao="4.00"><cStat>104</cStat><xMotivo>Lote processado</xMotivo>'
            + _prot(chave, "204", "Duplicidade de NF-e").replace(f' xmlns="{NFE}"', "")
            + "</retEnviNFe>"
        )

    fake.autorizacao = responder
    monkeypatch.setattr(nfe_service, "_build_sefaz_client", lambda certificate, env: fake)

    result = nfe_service.emit_nfe_sync(document.id)
    assert result.status == FiscalDocumentStatus.CANCELED
    assert result.xml_authorized is None


def test_rejeicao_guarda_codigo_e_motivo(fiscal_env, monkeypatch):
    document = fiscal_env["document"]
    fake = FakeClient()

    def responder(xml):
        return _ok(_ret_sincrono(_chave_do_lote(xml), "778", "Informado NCM inexistente"))

    fake.autorizacao = responder
    monkeypatch.setattr(nfe_service, "_build_sefaz_client", lambda certificate, env: fake)

    result = nfe_service.emit_nfe_sync(document.id)
    assert result.status == FiscalDocumentStatus.REJECTED
    assert result.error_code == "778"
    assert "NCM" in result.error_message


def _autorizar(document: FiscalDocument) -> None:
    document.status = FiscalDocumentStatus.AUTHORIZED
    document.access_key = "35261012345678000195550010000000151234567895"
    document.protocol = "135260000000042"
    db.session.commit()


def _ret_evento(c_stat: str, motivo: str) -> str:
    return (
        f'<retEnvEvento xmlns="{NFE}" versao="1.00"><idLote>1</idLote><cStat>128</cStat>'
        "<xMotivo>Lote de Evento Processado</xMotivo>"
        f'<retEvento versao="1.00"><infEvento><cStat>{c_stat}</cStat><xMotivo>{motivo}</xMotivo>'
        "<nProt>135260000000099</nProt></infEvento></retEvento></retEnvEvento>"
    )


def test_cancelamento_registrado(fiscal_env, monkeypatch):
    document = fiscal_env["document"]
    _autorizar(document)
    fake = FakeClient(evento=_ok(_ret_evento("135", "Evento registrado e vinculado a NF-e")))
    monkeypatch.setattr(nfe_service, "_build_sefaz_client", lambda certificate, env: fake)

    result = nfe_service.cancel_nfe_document(document.id, "Venda desfeita a pedido do cliente")
    assert result.status == FiscalDocumentStatus.CANCELED
    assert result.canceled_at is not None


def test_cancelamento_recusado_mantem_a_nota_autorizada(fiscal_env, monkeypatch):
    document = fiscal_env["document"]
    _autorizar(document)
    fake = FakeClient(evento=_ok(_ret_evento("501", "Prazo de cancelamento superior ao previsto")))
    monkeypatch.setattr(nfe_service, "_build_sefaz_client", lambda certificate, env: fake)

    result = nfe_service.cancel_nfe_document(document.id, "Venda desfeita a pedido do cliente")
    assert result.status == FiscalDocumentStatus.AUTHORIZED
    assert result.error_code == "501"
    evento = FiscalEvent.query.filter_by(document_id=document.id, event_type="cancelamento").one()
    assert "Prazo de cancelamento" in evento.error_message
