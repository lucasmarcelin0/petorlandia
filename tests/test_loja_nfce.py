"""NFC-e própria da loja: configuração, emissão, reenvio, cancelamento e telas.

A SEFAZ é trocada por um dublê que responde como a SEFAZ-SP; o XML enviado
é conferido contra o esquema oficial em cada emissão.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
import io
from pathlib import Path
import zipfile

import flask_login.utils as login_utils
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from extensions import db
from models import CasaDeRacao, LojaFiscalConfig, NfceDocumento, NfceEvento, User
from providers.nfce.xml_builder import ItemNfce, PagamentoNfce
from providers.nfe.sefaz_sp.client import SefazSoapResponse
from security.crypto import FERNET_PREFIX, clear_crypto_cache
from services.loja_fiscal import nfce_service
from services.loja_fiscal.nfce_service import NfceServiceError


NFE = "http://www.portalfiscal.inf.br/nfe"
XSD = Path(__file__).resolve().parent / "fixtures" / "nfe_xsd_v4" / "enviNFe_v4.00.xsd"
CNPJ = "12.345.678/0001-95"


def _pfx(cnpj_no_certificado: str | None = None) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    atributos = [x509.NameAttribute(NameOID.COMMON_NAME, "CAT DOG PET SHOP")]
    if cnpj_no_certificado:
        atributos.append(x509.NameAttribute(NameOID.SERIAL_NUMBER, f"CNPJ{cnpj_no_certificado}"))
    name = x509.Name(atributos)
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=200)).sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(b"a1", key, cert, None, serialization.BestAvailableEncryption(b"senha"))


@pytest.fixture()
def loja(app, monkeypatch):
    monkeypatch.setenv("FISCAL_MASTER_KEY", "chave-mestra-teste-nfce-loja")
    clear_crypto_cache()
    owner = User(name="Renato", email="renato-nfce@example.com")
    owner.set_password("x")
    outro = User(name="Outro", email="outro-nfce@example.com")
    outro.set_password("x")
    db.session.add_all([owner, outro])
    db.session.flush()
    casa = CasaDeRacao(nome="Cat Dog", tipo="petshop", owner_id=owner.id, status="ativa", cnpj=CNPJ)
    db.session.add(casa)
    db.session.flush()
    config = LojaFiscalConfig(
        casa_de_racao_id=casa.id,
        cnpj=CNPJ,
        razao_social="Cat Dog Pet Shop Ltda",
        nome_fantasia="Cat Dog",
        inscricao_estadual="481234567110",
        logradouro="Rua Oito",
        numero="2054A",
        bairro="Jardim Santa Rita",
        cep="14620000",
        serie=2,
    )
    db.session.add(config)
    db.session.flush()
    nfce_service.salvar_certificado(config, _pfx(), "senha")
    db.session.commit()
    return {"casa": casa, "config": config, "owner": owner, "outro": outro}


class FakeSefaz:
    """Responde como a SEFAZ-SP; guarda os lotes recebidos."""

    def __init__(self, schema=None):
        self.lotes: list[str] = []
        self.modo = "autoriza"
        self.consulta = "217"
        self.evento_cstat = "135"
        self.inut_cstat = "102"
        self.schema = schema
        self.ambientes: list[str] = []

    def _chave(self, lote: str) -> str:
        root = etree.fromstring(lote.encode("utf-8"))
        if self.schema is not None:
            assert self.schema.validate(root), "\n".join(str(e) for e in self.schema.error_log)
        return root.find(f".//{{{NFE}}}infNFe").get("Id")[3:]

    def autorizacao(self, lote):
        self.lotes.append(lote)
        chave = self._chave(lote)
        if self.modo == "timeout":
            return SefazSoapResponse(False, None, "<req/>", None, "Read timed out")
        c_stat, motivo = {
            "autoriza": ("100", "Autorizado o uso da NF-e"),
            "duplicidade": ("204", "Duplicidade de NF-e [nRec:351000000000001]"),
        }.get(self.modo, ("778", "Informado NCM inexistente"))
        ret = (
            f'<retEnviNFe xmlns="{NFE}" versao="4.00"><cStat>104</cStat><xMotivo>Lote processado</xMotivo>'
            f"<dhRecbto>2026-10-31T10:00:01-03:00</dhRecbto>"
            f'<protNFe versao="4.00"><infProt><tpAmb>2</tpAmb><chNFe>{chave}</chNFe>'
            f"<dhRecbto>2026-10-31T10:00:01-03:00</dhRecbto><nProt>135260000000123</nProt>"
            f"<cStat>{c_stat}</cStat><xMotivo>{motivo}</xMotivo></infProt></protNFe></retEnviNFe>"
        )
        return SefazSoapResponse(True, ret, "<req/>", f"<env>{ret}</env>")

    def consulta_protocolo(self, xml):
        chave = etree.fromstring(xml.encode()).find(f"{{{NFE}}}chNFe").text
        self.consultas = getattr(self, "consultas", []) + [chave]
        if self.consulta == "timeout":
            return SefazSoapResponse(False, None, "<req/>", None, "Read timed out")
        if self.consulta in {"100", "101"}:
            # Nota cancelada: cStat principal 101, protNFe com a autorização original (100).
            motivo = "Autorizado" if self.consulta == "100" else "Cancelamento de NF-e homologado"
            ret = (
                f'<retConsSitNFe xmlns="{NFE}" versao="4.00"><cStat>{self.consulta}</cStat><xMotivo>{motivo}</xMotivo>'
                f'<protNFe versao="4.00"><infProt><chNFe>{chave}</chNFe><nProt>135260000000999</nProt>'
                "<cStat>100</cStat><xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe></retConsSitNFe>"
            )
        else:
            ret = f'<retConsSitNFe xmlns="{NFE}" versao="4.00"><cStat>217</cStat><xMotivo>NF-e nao consta na base</xMotivo></retConsSitNFe>'
        return SefazSoapResponse(True, ret, "<req/>", f"<env>{ret}</env>")

    def recepcao_evento(self, xml):
        self.eventos = getattr(self, "eventos", []) + [xml]
        ret = (
            f'<retEnvEvento xmlns="{NFE}" versao="1.00"><idLote>1</idLote><cStat>128</cStat>'
            "<xMotivo>Lote de Evento Processado</xMotivo>"
            f'<retEvento versao="1.00"><infEvento><cStat>{self.evento_cstat}</cStat>'
            "<xMotivo>Evento registrado e vinculado a NFC-e</xMotivo><nProt>135260000000555</nProt>"
            "</infEvento></retEvento></retEnvEvento>"
        )
        return SefazSoapResponse(True, ret, "<req/>", f"<env>{ret}</env>")

    def inutilizacao(self, xml):
        ret = (
            f'<retInutNFe xmlns="{NFE}" versao="4.00"><infInut><cStat>{self.inut_cstat}</cStat>'
            "<xMotivo>Inutilizacao de numero homologado</xMotivo><nProt>135260000000777</nProt></infInut></retInutNFe>"
        )
        return SefazSoapResponse(True, ret, "<req/>", f"<env>{ret}</env>")

    def test_connection(self, c_uf="35"):
        return SefazSoapResponse(True, "<retConsStatServ/>", "<req/>", "<env/>")


@pytest.fixture()
def sefaz(monkeypatch):
    fake = FakeSefaz(schema=etree.XMLSchema(etree.parse(str(XSD))))

    def _cliente(config, ambiente=None):
        fake.ambientes.append(ambiente or config.ambiente)
        return fake

    monkeypatch.setattr(nfce_service, "_cliente", _cliente)
    return fake


def _item(**extra) -> ItemNfce:
    dados = dict(codigo="RAC-15", descricao="Ração 15kg", ncm="23091000", quantidade=Decimal("1"), valor_unitario=Decimal("189.90"))
    dados.update(extra)
    return ItemNfce(**dados)


def test_nota_teste_autorizada_e_xml_cifrado(loja, sefaz):
    config = loja["config"]
    documento = nfce_service.emitir_nota_teste(config, usuario_id=loja["owner"].id)

    assert documento.status == "autorizada"
    assert documento.numero == 1 and documento.serie == 2
    assert documento.protocolo == "135260000000123"
    assert documento.chave[20:22] == "65"
    assert "homologacao.nfce.fazenda.sp.gov.br" in documento.qrcode
    assert documento.qrcode.endswith(f"?p={documento.chave}|3|2")
    proc = etree.fromstring(documento.xml_autorizado.encode())
    assert proc.tag == f"{{{NFE}}}nfeProc"
    # Em repouso o XML fica cifrado com a chave da loja.
    assert documento._xml_autorizado.startswith(FERNET_PREFIX)
    assert config.ultimo_numero_homologacao == 1
    assert documento.payload_json["total_nota"] == "1.00"


def test_certificado_de_outro_cnpj_e_recusado(loja):
    with pytest.raises(NfceServiceError, match="outro CNPJ"):
        nfce_service.salvar_certificado(loja["config"], _pfx("11222333000181"), "senha")


def test_senha_errada_do_certificado(loja):
    with pytest.raises(NfceServiceError, match="senha"):
        nfce_service.salvar_certificado(loja["config"], _pfx(), "errada")


def test_dado_invalido_nao_consome_numero(loja, sefaz):
    config = loja["config"]
    with pytest.raises(NfceServiceError, match="NCM"):
        nfce_service.emitir_nfce(
            config,
            itens=[_item(ncm="")],
            pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal("200"))],
        )
    db.session.refresh(config)
    assert config.ultimo_numero_homologacao == 0
    assert NfceDocumento.query.count() == 0
    assert sefaz.lotes == []


def test_falha_de_rede_e_reenvio_dentro_da_janela(loja, sefaz):
    config = loja["config"]
    sefaz.modo = "timeout"
    documento = nfce_service.emitir_nfce(
        config, itens=[_item()], pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal("200"))], cpf="123.456.789-09"
    )
    assert documento.status == "erro"
    chave = documento.chave

    sefaz.modo = "autoriza"
    documento = nfce_service.reenviar_nfce(documento)
    assert documento.status == "autorizada"
    assert documento.chave == chave, "dentro da janela de 5 minutos reenvia o mesmo XML"
    assert len(sefaz.lotes) == 2


def test_reenvio_aproveita_autorizacao_que_chegou_na_sefaz(loja, sefaz):
    config = loja["config"]
    sefaz.modo = "timeout"
    documento = nfce_service.emitir_nfce(
        config, itens=[_item()], pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal("200"))]
    )
    assert documento.status == "erro"
    sefaz.consulta = "100"
    documento = nfce_service.reenviar_nfce(documento)
    assert documento.status == "autorizada"
    assert documento.protocolo == "135260000000999"
    assert len(sefaz.lotes) == 1, "não transmite de novo uma nota já autorizada"


def test_reenvio_nao_remonta_sem_resposta_conclusiva_da_sefaz(loja, sefaz):
    """Sem o 217 da SEFAZ, a chave original pode estar autorizada: nada muda."""
    config = loja["config"]
    sefaz.modo = "timeout"
    documento = nfce_service.emitir_nfce(
        config, itens=[_item()], pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal("200"))]
    )
    chave, xml = documento.chave, documento.xml_assinado
    documento.dh_emi = "2026-10-31T08:00:00-03:00"  # fora da janela: remontaria
    db.session.commit()

    sefaz.consulta = "timeout"
    with pytest.raises(NfceServiceError, match="Nada foi alterado"):
        nfce_service.reenviar_nfce(documento)
    documento = db.session.get(NfceDocumento, documento.id)
    assert documento.status == "erro"
    assert documento.chave == chave and documento.xml_assinado == xml
    assert len(sefaz.lotes) == 1

    # Com a confirmação de que a chave não existe, remonta (mesmo número).
    sefaz.consulta = "217"
    sefaz.modo = "autoriza"
    documento = nfce_service.reenviar_nfce(documento)
    assert documento.status == "autorizada" and documento.chave != chave
    assert documento.numero == 1


def test_duplicidade_sem_confirmacao_fica_recuperavel(loja, sefaz):
    config = loja["config"]
    sefaz.modo = "duplicidade"
    sefaz.consulta = "timeout"
    documento = nfce_service.emitir_nfce(
        config, itens=[_item()], pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal("200"))]
    )
    assert documento.status == "erro", "não vira rejeição definitiva"
    assert documento.c_stat == "204"

    sefaz.consulta = "100"
    documento = nfce_service.reenviar_nfce(documento)
    assert documento.status == "autorizada"
    assert len(sefaz.lotes) == 1, "a mesma chave é recuperada sem transmitir de novo"


def test_consulta_de_nota_cancelada_nao_vira_autorizada(loja, sefaz):
    config = loja["config"]
    sefaz.modo = "timeout"
    documento = nfce_service.emitir_nfce(
        config, itens=[_item()], pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal("200"))]
    )
    sefaz.consulta = "101"
    documento = nfce_service.reenviar_nfce(documento)
    assert documento.status == "cancelada"
    assert documento.c_stat == "101"
    assert documento.xml_autorizado is None
    assert len(sefaz.lotes) == 1


def test_nota_de_teste_continua_em_homologacao_depois_da_troca(loja, sefaz):
    """Trocar a loja para produção não manda nota de teste para a produção."""
    config = loja["config"]
    sefaz.modo = "timeout"
    documento = nfce_service.emitir_nfce(
        config, itens=[_item()], pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal("200"))]
    )
    assert documento.ambiente == "homologacao"
    documento.dh_emi = "2026-10-31T08:00:00-03:00"
    config.ambiente = "producao"
    db.session.commit()
    sefaz.ambientes.clear()

    sefaz.modo = "autoriza"
    documento = nfce_service.reenviar_nfce(documento)
    assert documento.status == "autorizada"
    assert set(sefaz.ambientes) == {"homologacao"}
    nfe = etree.fromstring(sefaz.lotes[-1].encode())
    assert nfe.find(f".//{{{NFE}}}ide/{{{NFE}}}tpAmb").text == "2"
    assert documento.qrcode.endswith("|3|2") and "homologacao" in documento.qrcode
    assert config.ultimo_numero_producao == 0

    sefaz.ambientes.clear()
    nfce_service.cancelar_nfce(documento, "Teste de cancelamento em homologacao")
    assert set(sefaz.ambientes) == {"homologacao"}


def test_rejeitada_remonta_com_mesmo_numero_e_nova_chave(loja, sefaz):
    config = loja["config"]
    sefaz.modo = "rejeita"
    documento = nfce_service.emitir_nfce(
        config, itens=[_item()], pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal("200"))]
    )
    assert documento.status == "rejeitada" and documento.c_stat == "778"
    numero, chave = documento.numero, documento.chave

    sefaz.modo = "autoriza"
    documento = nfce_service.reenviar_nfce(documento, itens=[_item(ncm="23091090")])
    assert documento.status == "autorizada"
    assert documento.numero == numero
    assert documento.chave != chave
    assert config.ultimo_numero_homologacao == 1


def test_cancelamento_guarda_proc_evento(loja, sefaz):
    documento = nfce_service.emitir_nota_teste(loja["config"])
    with pytest.raises(NfceServiceError, match="15 caracteres"):
        nfce_service.cancelar_nfce(documento, "curto")
    documento = nfce_service.cancelar_nfce(documento, "Cliente desistiu da compra no caixa")
    assert documento.status == "cancelada"
    assert documento.cancel_protocolo == "135260000000555"
    proc = etree.fromstring(documento.xml_cancelamento.encode())
    assert proc.tag == f"{{{NFE}}}procEventoNFe"
    assert proc.find(f"{{{NFE}}}evento") is not None and proc.find(f"{{{NFE}}}retEvento") is not None


def test_cancelamento_recusado_mantem_autorizada(loja, sefaz):
    documento = nfce_service.emitir_nota_teste(loja["config"])
    sefaz.evento_cstat = "501"
    with pytest.raises(NfceServiceError, match="não aceitou"):
        nfce_service.cancelar_nfce(documento, "Cliente desistiu da compra no caixa")
    assert documento.status == "autorizada"


def test_inutilizacao_de_numero_reservado(loja, sefaz):
    config = loja["config"]
    sefaz.modo = "rejeita"
    documento = nfce_service.emitir_nfce(
        config, itens=[_item()], pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal("200"))]
    )
    with pytest.raises(NfceServiceError, match="já reservou"):
        nfce_service.inutilizar_numeros(config, 5, 6, "Numeracao pulada por falha")
    protocolo = nfce_service.inutilizar_numeros(config, 1, 1, "Nota rejeitada e abandonada no caixa")
    assert protocolo == "135260000000777"
    db.session.refresh(documento)
    assert documento.status == "inutilizada"
    assert NfceEvento.query.filter_by(tipo="inutilizacao", status="homologada").count() == 1


def test_inutilizacao_nao_aceita_nota_autorizada(loja, sefaz):
    config = loja["config"]
    nfce_service.emitir_nota_teste(config)
    with pytest.raises(NfceServiceError, match="autorizada"):
        nfce_service.inutilizar_numeros(config, 1, 1, "Tentativa indevida de inutilizar")


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def test_rotas_exigem_dono_da_loja(loja, client, monkeypatch):
    # O app responde 404 a quem não tem acesso, para não revelar a loja.
    _login(monkeypatch, loja["outro"])
    casa_id = loja["casa"].id
    assert client.get(f"/casa-de-racao/{casa_id}/fiscal").status_code == 404
    assert client.get(f"/casa-de-racao/{casa_id}/nfce").status_code == 404
    assert client.post(f"/casa-de-racao/{casa_id}/fiscal/nota-teste").status_code == 404
    assert NfceDocumento.query.count() == 0


def test_tela_de_configuracao_e_salvar_dados(loja, client, monkeypatch):
    _login(monkeypatch, loja["owner"])
    casa_id = loja["casa"].id
    resp = client.get(f"/casa-de-racao/{casa_id}/fiscal")
    assert resp.status_code == 200
    assert "Certificado digital A1" in resp.get_data(as_text=True)

    resp = client.post(
        f"/casa-de-racao/{casa_id}/fiscal",
        data={
            "cnpj": CNPJ,
            "razao_social": "Cat Dog Pet Shop Ltda",
            "inscricao_estadual": "481.234.567.110",
            "logradouro": "Rua Oito",
            "numero": "2054A",
            "bairro": "Jardim Santa Rita",
            "municipio": "Orlândia",
            "codigo_municipio": "3534302",
            "serie": "3",
            "csosn_padrao": "500",
            "percentual_tributos": "12,5",
            "ativo": "1",
        },
    )
    assert resp.status_code == 302
    config = LojaFiscalConfig.query.filter_by(casa_de_racao_id=casa_id).one()
    assert config.serie == 3
    assert config.csosn_padrao == "500"
    assert config.percentual_tributos == Decimal("12.50")
    assert config.ativo is True


def test_cnpj_invalido_nao_salva(loja, client, monkeypatch):
    _login(monkeypatch, loja["owner"])
    casa_id = loja["casa"].id
    resp = client.post(f"/casa-de-racao/{casa_id}/fiscal", data={"cnpj": "11.111.111/1111-11"}, follow_redirects=True)
    assert "CNPJ inválido" in resp.get_data(as_text=True)
    assert LojaFiscalConfig.query.filter_by(casa_de_racao_id=casa_id).one().serie == 2


def test_producao_exige_teste_autorizado(loja, sefaz, client, monkeypatch):
    _login(monkeypatch, loja["owner"])
    casa_id = loja["casa"].id
    client.post(f"/casa-de-racao/{casa_id}/fiscal/ambiente", data={"ambiente": "producao", "confirmacao": "PRODUCAO"})
    assert LojaFiscalConfig.query.get(loja["config"].id).ambiente == "homologacao"

    client.post(f"/casa-de-racao/{casa_id}/fiscal/nota-teste")
    client.post(f"/casa-de-racao/{casa_id}/fiscal/ambiente", data={"ambiente": "producao", "confirmacao": "PRODUCAO"})
    config = LojaFiscalConfig.query.get(loja["config"].id)
    assert config.ambiente == "producao"
    assert config.ultimo_numero_producao == 0, "a numeração de produção começa do zero"


def test_cupom_xml_e_zip_do_mes(loja, sefaz, client, monkeypatch):
    _login(monkeypatch, loja["owner"])
    config = loja["config"]
    casa_id = loja["casa"].id
    documento = nfce_service.emitir_nfce(
        config,
        itens=[_item(), _item(codigo="BISC", descricao="Biscoito", valor_unitario=Decimal("10.10"))],
        pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal("250"))],
        cpf="123.456.789-09",
    )
    cupom = client.get(f"/casa-de-racao/{casa_id}/nfce/{documento.id}/cupom")
    html = cupom.get_data(as_text=True)
    assert cupom.status_code == 200
    assert "data:image/png;base64," in html
    assert "HOMOLOGAÇÃO" in html
    assert "CONSUMIDOR CPF: 123.456.789-09" in html
    assert "Troco R$" in html and "50.00" in html

    xml = client.get(f"/casa-de-racao/{casa_id}/nfce/{documento.id}/xml")
    assert xml.status_code == 200 and b"nfeProc" in xml.data

    # O ZIP do contador traz só produção.
    documento.ambiente = "producao"
    db.session.commit()
    mes = documento.dh_emi[:7]
    resp = client.get(f"/casa-de-racao/{casa_id}/nfce/xmls?mes={mes}")
    assert resp.status_code == 200
    nomes = zipfile.ZipFile(io.BytesIO(resp.data)).namelist()
    assert nomes == [f"{documento.chave}-procNFe.xml"]
    assert client.get(f"/casa-de-racao/{casa_id}/nfce/xmls?mes=2026-13").status_code == 400


def test_lista_e_detalhe(loja, sefaz, client, monkeypatch):
    _login(monkeypatch, loja["owner"])
    documento = nfce_service.emitir_nota_teste(loja["config"])
    casa_id = loja["casa"].id
    lista = client.get(f"/casa-de-racao/{casa_id}/nfce")
    assert lista.status_code == 200 and "Autorizada" in lista.get_data(as_text=True)
    detalhe = client.get(f"/casa-de-racao/{casa_id}/nfce/{documento.id}")
    assert detalhe.status_code == 200 and documento.chave in detalhe.get_data(as_text=True)
    assert client.get(f"/casa-de-racao/{casa_id}/nfce/999999").status_code == 404
