"""Notas de compra baixadas da SEFAZ (distribuição DF-e) para a loja."""
from __future__ import annotations

import base64
import datetime
import gzip

import flask_login.utils as login_utils
import pytest
from lxml import etree

from extensions import db
from models import (
    CasaDeRacao,
    LojaDfeControle,
    LojaDfeDocumento,
    LojaEntradaNota,
    LojaFiscalConfig,
    User,
)
from providers.fiscal.sefaz_soap import build_soap12_envelope, extract_result_body
from providers.nfe.distribuicao import (
    build_cons_chave_xml,
    build_dist_nsu_xml,
    build_evento_ciencia_xml,
    parse_resumo_nfe,
    parse_retorno_distribuicao,
)
from providers.nfe.sefaz_sp.client import SefazSoapResponse
from security.crypto import clear_crypto_cache
from services.loja_caixa import dfe
from services.loja_caixa.dfe import DfeError
from services.loja_fiscal import nfce_service
from test_loja_entrada import CNPJ_LOJA, _nota
from test_loja_nfce import _pfx

NFE = "http://www.portalfiscal.inf.br/nfe"
DSIG = "http://www.w3.org/2000/09/xmldsig#"
CHAVE_RESUMO = "35261011222333000181550010000077771123456780"


def _zip(xml: str | bytes) -> str:
    dados = xml.encode("utf-8") if isinstance(xml, str) else xml
    return base64.b64encode(gzip.compress(dados)).decode("ascii")


def _resumo(chave=CHAVE_RESUMO, situacao="1") -> str:
    return (
        f'<resNFe xmlns="{NFE}" versao="1.01"><chNFe>{chave}</chNFe><CNPJ>11222333000181</CNPJ>'
        "<xNome>DISTRIBUIDORA PET LTDA</xNome><IE>123</IE><dhEmi>2026-10-29T09:00:00-03:00</dhEmi>"
        "<tpNF>1</tpNF><vNF>512.30</vNF><digVal>abc=</digVal><dhRecbto>2026-10-29T09:00:05-03:00</dhRecbto>"
        f"<nProt>135260000005555</nProt><cSitNFe>{situacao}</cSitNFe></resNFe>"
    )


def _evento_cancelamento(chave: str) -> str:
    return (
        f'<resEvento xmlns="{NFE}" versao="1.01"><cOrgao>35</cOrgao><CNPJ>11222333000181</CNPJ>'
        f"<chNFe>{chave}</chNFe><dhEvento>2026-10-29T10:00:00-03:00</dhEvento><tpEvento>110111</tpEvento>"
        "<nSeqEvento>1</nSeqEvento><xEvento>Cancelamento</xEvento><dhRecbto>2026-10-29T10:00:01-03:00</dhRecbto>"
        "<nProt>135260000006666</nProt></resEvento>"
    )


def _ret(c_stat: str, docs: list[tuple[str, str, str]], ult="000000000000003", maximo="000000000000003") -> str:
    lote = "".join(f'<docZip NSU="{nsu}" schema="{schema}">{_zip(xml)}</docZip>' for nsu, schema, xml in docs)
    return (
        f'<retDistDFeInt xmlns="{NFE}" versao="1.01"><tpAmb>1</tpAmb><verAplic>1</verAplic>'
        f"<cStat>{c_stat}</cStat><xMotivo>{'Documento localizado' if c_stat == '138' else 'Nenhum documento localizado'}</xMotivo>"
        f"<dhResp>2026-10-31T20:00:00-03:00</dhResp><ultNSU>{ult}</ultNSU><maxNSU>{maximo}</maxNSU>"
        + (f"<loteDistDFeInt>{lote}</loteDistDFeInt>" if lote else "")
        + "</retDistDFeInt>"
    )


class FakeNacional:
    def __init__(self):
        self.respostas: list[str] = []
        self.pedidos: list[str] = []
        self.eventos: list[str] = []
        self.evento_cstat = "135"
        self.por_chave: dict[str, str] = {}

    def distribuicao(self, xml):
        self.pedidos.append(xml)
        raiz = etree.fromstring(xml.encode())
        chave = raiz.find(f".//{{{NFE}}}chNFe")
        if chave is not None:
            procnfe = self.por_chave.get(chave.text)
            ret = _ret("138", [("000000000000009", "procNFe_v4.00.xsd", procnfe)]) if procnfe else _ret("137", [])
            return SefazSoapResponse(True, ret, "<req/>", f"<env>{ret}</env>")
        ret = self.respostas.pop(0) if self.respostas else _ret("137", [])
        return SefazSoapResponse(True, ret, "<req/>", f"<env>{ret}</env>")

    def evento(self, xml):
        self.eventos.append(xml)
        ret = (
            f'<retEnvEvento xmlns="{NFE}" versao="1.00"><idLote>1</idLote><cStat>128</cStat><xMotivo>Lote processado</xMotivo>'
            f'<retEvento versao="1.00"><infEvento><cStat>{self.evento_cstat}</cStat><xMotivo>Evento registrado</xMotivo>'
            "<nProt>891260000000001</nProt></infEvento></retEvento></retEnvEvento>"
        )
        return SefazSoapResponse(True, ret, "<req/>", f"<env>{ret}</env>")


@pytest.fixture()
def loja(app, monkeypatch):
    monkeypatch.setenv("FISCAL_MASTER_KEY", "chave-mestra-teste-dfe-loja")
    clear_crypto_cache()
    owner = User(name="Renato", email="renato-dfe@example.com")
    owner.set_password("x")
    outro = User(name="Outro", email="outro-dfe@example.com")
    outro.set_password("x")
    db.session.add_all([owner, outro])
    db.session.flush()
    casa = CasaDeRacao(nome="Cat Dog", owner_id=owner.id, status="ativa", cnpj=CNPJ_LOJA)
    db.session.add(casa)
    db.session.flush()
    config = LojaFiscalConfig(
        casa_de_racao_id=casa.id, cnpj=CNPJ_LOJA, razao_social="Cat Dog Ltda", inscricao_estadual="481234567110",
        logradouro="Rua Oito", numero="2054A", bairro="Jardim Santa Rita", ambiente="producao",
    )
    db.session.add(config)
    db.session.flush()
    nfce_service.salvar_certificado(config, _pfx(), "senha")
    db.session.commit()
    fake = FakeNacional()
    monkeypatch.setattr(dfe, "_cliente", lambda cfg: fake)
    return {"casa": casa, "config": config, "owner": owner, "outro": outro, "sefaz": fake}


def _agora(hora=20, minuto=0):
    return datetime.datetime(2026, 10, 31, hora, minuto, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))


# ----------------------------------------------------------------- unidade

def test_xmls_do_servico_nacional():
    pedido = etree.fromstring(build_dist_nsu_xml(tp_amb="1", c_uf_autor="35", cnpj="12.345.678/0001-95", ult_nsu=42).encode())
    assert pedido.get("versao") == "1.01"
    assert pedido.find(f"{{{NFE}}}distNSU/{{{NFE}}}ultNSU").text == "000000000000042"
    por_chave = etree.fromstring(build_cons_chave_xml(tp_amb="1", c_uf_autor="35", cnpj=CNPJ_LOJA, chave=CHAVE_RESUMO).encode())
    assert por_chave.find(f"{{{NFE}}}consChNFe/{{{NFE}}}chNFe").text == CHAVE_RESUMO
    evento = etree.fromstring(build_evento_ciencia_xml(chave=CHAVE_RESUMO, cnpj=CNPJ_LOJA, tp_amb="1").encode())
    inf = evento.find(f"{{{NFE}}}evento/{{{NFE}}}infEvento")
    assert inf.get("Id") == f"ID210210{CHAVE_RESUMO}01"
    assert inf.find(f"{{{NFE}}}cOrgao").text == "91"
    assert inf.find(f"{{{NFE}}}detEvento/{{{NFE}}}descEvento").text == "Ciencia da Operacao"


def test_envelope_da_distribuicao_tem_a_operacao():
    envelope = etree.fromstring(build_soap12_envelope("NFeDistribuicaoDFe", "<distDFeInt/>", "nfeDistDFeInteresse").encode())
    op = envelope.find(".//{http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe}nfeDistDFeInteresse")
    assert op is not None
    assert op.find("{http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe}nfeDadosMsg") is not None
    resposta = (
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"><soap:Body>'
        '<nfeDistDFeInteresseResponse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">'
        f"<nfeDistDFeInteresseResult>{_ret('137', [])}</nfeDistDFeInteresseResult>"
        "</nfeDistDFeInteresseResponse></soap:Body></soap:Envelope>"
    )
    corpo, erro = extract_result_body(resposta, ("nfeDistDFeInteresseResult",))
    assert erro is None and "retDistDFeInt" in corpo
    # Os serviços 4.00 continuam iguais.
    assert extract_result_body(resposta)[0] is None


def test_le_lote_compactado():
    retorno = parse_retorno_distribuicao(
        _ret("138", [("000000000000001", "resNFe_v1.01.xsd", _resumo())], ult="000000000000001", maximo="000000000000005")
    )
    assert retorno.c_stat == "138" and retorno.ult_nsu == "000000000000001"
    assert retorno.documentos[0].tipo == "resumo"
    resumo = parse_resumo_nfe(retorno.documentos[0].xml)
    assert resumo.chave == CHAVE_RESUMO and resumo.valor == "512.30" and resumo.situacao == "1"


# --------------------------------------------------------------- serviço

def test_busca_guarda_resumo_importa_completa_e_marca_cancelada(loja):
    casa, sefaz = loja["casa"], loja["sefaz"]
    nota_completa = _nota(numero="555").decode()
    chave_completa = etree.fromstring(nota_completa.encode()).find(f".//{{{NFE}}}infNFe").get("Id")[3:]
    chave_cancelada = "35261011222333000181550010000088881123456789"
    sefaz.respostas = [
        _ret(
            "138",
            [
                ("000000000000001", "resNFe_v1.01.xsd", _resumo()),
                ("000000000000002", "procNFe_v4.00.xsd", nota_completa),
                ("000000000000003", "resNFe_v1.01.xsd", _resumo(chave=chave_cancelada)),
            ],
            ult="000000000000003",
            maximo="000000000000004",
        ),
        _ret("138", [("000000000000004", "resEvento_v1.01.xsd", _evento_cancelamento(chave_cancelada))],
             ult="000000000000004", maximo="000000000000004"),
    ]
    resultado = dfe.buscar_notas(casa, agora=_agora())
    assert resultado["novas"] == 3
    assert len(sefaz.pedidos) == 2, "segue o próximo lote enquanto há documentos"
    ctl = LojaDfeControle.query.one()
    assert ctl.ult_nsu == "000000000000004"
    assert dfe.pode_consultar(ctl, _agora(20, 30)) is False
    assert dfe.pode_consultar(ctl, _agora(21, 1)) is True

    completa = LojaDfeDocumento.query.filter_by(chave=chave_completa).one()
    assert completa.entrada_id is not None
    entrada = db.session.get(LojaEntradaNota, completa.entrada_id)
    assert entrada.origem == "sefaz" and entrada.status == "rascunho"
    assert LojaDfeDocumento.query.filter_by(chave=chave_cancelada).one().situacao == "3"

    with pytest.raises(DfeError, match="uma por hora"):
        dfe.buscar_notas(casa, agora=_agora(20, 30))


def test_baixar_nota_registra_ciencia_e_traz_o_xml(loja):
    casa, sefaz = loja["casa"], loja["sefaz"]
    sefaz.respostas = [_ret("138", [("000000000000001", "resNFe_v1.01.xsd", _resumo())], ult="000000000000001", maximo="000000000000001")]
    dfe.buscar_notas(casa, agora=_agora())
    doc = LojaDfeDocumento.query.one()
    assert doc.xml_completo is None and doc.entrada_id is None

    xml = _nota(numero="7777").decode()
    raiz = etree.fromstring(xml.encode())
    raiz.find(f".//{{{NFE}}}infNFe").set("Id", f"NFe{CHAVE_RESUMO}")
    sefaz.por_chave[CHAVE_RESUMO] = etree.tostring(raiz, encoding="unicode")

    doc = dfe.baixar_nota(casa, doc)
    assert doc.ciencia_em is not None
    assert doc.entrada_id is not None
    evento = etree.fromstring(sefaz.eventos[0].encode())
    assert evento.find(f".//{{{NFE}}}tpEvento").text == "210210"
    assert evento.find(f".//{{{DSIG}}}Signature") is not None, "evento vai assinado com o A1 da loja"


def test_ciencia_recusada_mostra_o_motivo(loja):
    casa, sefaz = loja["casa"], loja["sefaz"]
    sefaz.respostas = [_ret("138", [("000000000000001", "resNFe_v1.01.xsd", _resumo())], ult="000000000000001", maximo="000000000000001")]
    dfe.buscar_notas(casa, agora=_agora())
    doc = LojaDfeDocumento.query.one()
    sefaz.evento_cstat = "596"
    with pytest.raises(DfeError, match="não registrou a ciência"):
        dfe.baixar_nota(casa, doc)
    assert doc.ciencia_em is None and doc.erro


def test_rotina_horaria_baixa_sozinha_quando_ligado(loja):
    casa, sefaz = loja["casa"], loja["sefaz"]
    ctl = dfe.controle(casa)
    ctl.ciencia_automatica = True
    db.session.commit()
    sefaz.respostas = [_ret("138", [("000000000000001", "resNFe_v1.01.xsd", _resumo())], ult="000000000000001", maximo="000000000000001")]
    xml = _nota(numero="7777").decode()
    raiz = etree.fromstring(xml.encode())
    raiz.find(f".//{{{NFE}}}infNFe").set("Id", f"NFe{CHAVE_RESUMO}")
    sefaz.por_chave[CHAVE_RESUMO] = etree.tostring(raiz, encoding="unicode")

    resumo = dfe.rotina_horaria(agora=_agora())
    assert resumo == {"lojas": 1, "novas": 1, "baixadas": 1, "erros": 0}
    assert LojaEntradaNota.query.filter_by(origem="sefaz").count() == 1
    # Dentro da mesma hora, a rotina não consulta de novo.
    assert dfe.rotina_horaria(agora=_agora(20, 40))["lojas"] == 0


def test_sem_certificado_explica_o_que_falta(app):
    owner = User(name="Sem cert", email="sem-cert-dfe@example.com")
    owner.set_password("x")
    db.session.add(owner)
    db.session.flush()
    casa = CasaDeRacao(nome="Sem cert", owner_id=owner.id, status="ativa")
    db.session.add(casa)
    db.session.commit()
    with pytest.raises(DfeError, match="certificado A1"):
        dfe.buscar_notas(casa)


# ------------------------------------------------------------------- telas

def test_telas_da_sefaz(loja, client, monkeypatch):
    monkeypatch.setattr(login_utils, "_get_user", lambda: loja["owner"])
    casa_id, sefaz = loja["casa"].id, loja["sefaz"]
    sefaz.respostas = [_ret("138", [("000000000000001", "resNFe_v1.01.xsd", _resumo())], ult="000000000000001", maximo="000000000000001")]
    pagina = client.get(f"/casa-de-racao/{casa_id}/estoque/entradas").get_data(as_text=True)
    assert "Buscar notas agora" in pagina
    assert client.post(f"/casa-de-racao/{casa_id}/estoque/entradas/sefaz/buscar").status_code == 302
    pagina = client.get(f"/casa-de-racao/{casa_id}/estoque/entradas").get_data(as_text=True)
    assert "DISTRIBUIDORA PET LTDA" in pagina and "Baixar XML" in pagina

    assert client.post(f"/casa-de-racao/{casa_id}/estoque/entradas/sefaz/automatico", data={"ciencia_automatica": "1"}).status_code == 302
    assert LojaDfeControle.query.one().ciencia_automatica is True

    xml = _nota(numero="7777").decode()
    raiz = etree.fromstring(xml.encode())
    raiz.find(f".//{{{NFE}}}infNFe").set("Id", f"NFe{CHAVE_RESUMO}")
    sefaz.por_chave[CHAVE_RESUMO] = etree.tostring(raiz, encoding="unicode")
    doc = LojaDfeDocumento.query.one()
    resposta = client.post(f"/casa-de-racao/{casa_id}/estoque/entradas/sefaz/{doc.id}/baixar")
    assert resposta.status_code == 302 and "/estoque/entradas/" in resposta.headers["Location"]
    assert LojaEntradaNota.query.count() == 1

    monkeypatch.setattr(login_utils, "_get_user", lambda: loja["outro"])
    assert client.post(f"/casa-de-racao/{casa_id}/estoque/entradas/sefaz/buscar").status_code == 404
    assert client.post(f"/casa-de-racao/{casa_id}/estoque/entradas/sefaz/{doc.id}/baixar").status_code == 404
