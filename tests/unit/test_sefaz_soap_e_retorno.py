"""Transporte SOAP 1.2 da SEFAZ e leitura dos retornos (lote x nota)."""
from __future__ import annotations

import pytest
import requests
from lxml import etree

from providers.fiscal import sefaz_soap
from providers.fiscal.sefaz_soap import build_soap12_envelope, extract_result_body, post_soap12
from providers.nfe.retorno import parse_autorizacao, parse_consulta_situacao, parse_evento, parse_inutilizacao
from providers.nfe.sefaz_sp.client import (
    SefazSpNfeClient,
    get_sefaz_sp_nfce_config,
    get_sefaz_sp_wsdl_config,
)


NFE = "http://www.portalfiscal.inf.br/nfe"
CHAVE = "35261012345678000195650010000000011234567891"


def _envelope(service: str, inner: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"><soap:Body>'
        f'<nfeResultMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/{service}">{inner}</nfeResultMsg>'
        "</soap:Body></soap:Envelope>"
    )


RET_SINCRONO_AUTORIZADO = (
    f'<retEnviNFe xmlns="{NFE}" versao="4.00"><tpAmb>2</tpAmb><verAplic>SP_NFCE_PL_009_V400</verAplic>'
    "<cStat>104</cStat><xMotivo>Lote processado</xMotivo><cUF>35</cUF>"
    "<dhRecbto>2026-10-31T10:00:00-03:00</dhRecbto>"
    '<protNFe versao="4.00"><infProt><tpAmb>2</tpAmb><verAplic>SP</verAplic>'
    f"<chNFe>{CHAVE}</chNFe><dhRecbto>2026-10-31T10:00:00-03:00</dhRecbto>"
    "<nProt>135260000012345</nProt><digVal>abc=</digVal><cStat>100</cStat>"
    "<xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe></retEnviNFe>"
)


def test_envelope_leva_o_xml_como_xml_e_sem_declaracao():
    envelope = build_soap12_envelope("NFeAutorizacao4", '<?xml version="1.0"?><enviNFe xmlns="urn:x"/>')
    root = etree.fromstring(envelope.encode("utf-8"))
    dados = root.find(".//{http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4}nfeDadosMsg")
    assert dados is not None
    assert dados[0].tag == "{urn:x}enviNFe", "o lote deve ir como elemento, não como texto escapado"
    assert envelope.count("<?xml") == 1


def test_extrai_retorno_de_dentro_do_nfe_result_msg():
    body, fault = extract_result_body(_envelope("NFeAutorizacao4", RET_SINCRONO_AUTORIZADO))
    assert fault is None
    assert etree.fromstring(body.encode()).tag == f"{{{NFE}}}retEnviNFe"


def test_soap_fault_vira_mensagem():
    fault = (
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"><soap:Body><soap:Fault>'
        "<soap:Reason><soap:Text>Certificado nao autorizado</soap:Text></soap:Reason>"
        "</soap:Fault></soap:Body></soap:Envelope>"
    )
    body, message = extract_result_body(fault)
    assert body is None
    assert "Certificado nao autorizado" in message


class _FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.encoding = "utf-8"


def test_post_envia_soap12_com_certificado_e_tls_ativo(monkeypatch):
    captured = {}

    def fake_post(url, data, headers, cert, timeout, verify):
        captured.update(url=url, data=data, headers=headers, cert=cert, timeout=timeout, verify=verify)
        return _FakeResponse(200, _envelope("NFeAutorizacao4", RET_SINCRONO_AUTORIZADO))

    monkeypatch.setattr(sefaz_soap.requests, "post", fake_post)
    monkeypatch.delenv("SEFAZ_CA_BUNDLE", raising=False)
    result = post_soap12(
        "https://homologacao.nfce.fazenda.sp.gov.br/ws/NFeAutorizacao4.asmx",
        "NFeAutorizacao4",
        "nfeAutorizacaoLote",
        f'<enviNFe xmlns="{NFE}" versao="4.00"/>',
        cert_files=("/tmp/cert.pem", "/tmp/key.pem"),
    )
    assert result.ok
    assert captured["cert"] == ("/tmp/cert.pem", "/tmp/key.pem")
    assert captured["verify"] is True, "a validação TLS nunca é desligada"
    assert captured["headers"]["Content-Type"].startswith("application/soap+xml")
    assert 'action="http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4/nfeAutorizacaoLote"' in (
        captured["headers"]["Content-Type"]
    )
    assert parse_autorizacao(result.body_xml).autorizado


def test_post_usa_bundle_de_cas_configurado(monkeypatch):
    seen = {}

    def fake_post(url, data, headers, cert, timeout, verify):
        seen["verify"] = verify
        return _FakeResponse(200, _envelope("NFeStatusServico4", f'<retConsStatServ xmlns="{NFE}"/>'))

    monkeypatch.setattr(sefaz_soap.requests, "post", fake_post)
    monkeypatch.setenv("SEFAZ_CA_BUNDLE", "/etc/ssl/icp-brasil.pem")
    post_soap12("https://x/ws", "NFeStatusServico4", "nfeStatusServicoNF", "<a/>", cert_files=None)
    assert seen["verify"] == "/etc/ssl/icp-brasil.pem"


def test_falha_de_rede_nao_estoura(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.ConnectTimeout("timeout")

    monkeypatch.setattr(sefaz_soap.requests, "post", fake_post)
    result = post_soap12("https://x/ws", "NFeAutorizacao4", "nfeAutorizacaoLote", "<a/>", cert_files=None)
    assert not result.ok
    assert "timeout" in result.error_message


def test_retorno_sincrono_le_o_cstat_da_nota_e_nao_o_do_lote():
    retorno = parse_autorizacao(RET_SINCRONO_AUTORIZADO)
    assert retorno.c_stat_lote == "104"
    assert retorno.c_stat == "100"
    assert retorno.autorizado
    assert retorno.n_prot == "135260000012345"
    assert retorno.ch_nfe == CHAVE
    assert "protNFe" in retorno.prot_nfe_xml


def test_retorno_sincrono_com_rejeicao_da_nota():
    xml = RET_SINCRONO_AUTORIZADO.replace("<cStat>100</cStat>", "<cStat>539</cStat>").replace(
        "Autorizado o uso da NF-e", "Duplicidade de NF-e com diferenca na Chave de Acesso"
    )
    retorno = parse_autorizacao(xml)
    assert not retorno.autorizado
    assert retorno.c_stat == "539"


def test_lote_assincrono_em_processamento():
    xml = (
        f'<retEnviNFe xmlns="{NFE}" versao="4.00"><tpAmb>2</tpAmb><cStat>103</cStat>'
        "<xMotivo>Lote recebido com sucesso</xMotivo><infRec><nRec>351000000000001</nRec>"
        "<tMed>1</tMed></infRec></retEnviNFe>"
    )
    retorno = parse_autorizacao(xml)
    assert retorno.em_processamento
    assert retorno.n_rec == "351000000000001"


def test_rejeicao_do_lote_sem_protocolo():
    xml = f'<retEnviNFe xmlns="{NFE}" versao="4.00"><cStat>452</cStat><xMotivo>Solicitada resposta assincrona</xMotivo></retEnviNFe>'
    retorno = parse_autorizacao(xml)
    assert retorno.c_stat == "452"
    assert not retorno.autorizado and not retorno.em_processamento


def test_evento_le_o_cstat_do_evento_e_nao_o_do_lote():
    xml = (
        f'<retEnvEvento xmlns="{NFE}" versao="1.00"><idLote>1</idLote><tpAmb>2</tpAmb><cOrgao>35</cOrgao>'
        "<cStat>128</cStat><xMotivo>Lote de Evento Processado</xMotivo>"
        '<retEvento versao="1.00"><infEvento><tpAmb>2</tpAmb><cOrgao>35</cOrgao><cStat>135</cStat>'
        "<xMotivo>Evento registrado e vinculado a NF-e</xMotivo><nProt>135260000099999</nProt>"
        "</infEvento></retEvento></retEnvEvento>"
    )
    retorno = parse_evento(xml)
    assert retorno.c_stat_lote == "128"
    assert retorno.registrado
    assert retorno.n_prot == "135260000099999"


def test_consulta_situacao_autorizada():
    xml = (
        f'<retConsSitNFe xmlns="{NFE}" versao="4.00"><tpAmb>2</tpAmb><cStat>100</cStat>'
        "<xMotivo>Autorizado o uso da NF-e</xMotivo>"
        f'<protNFe versao="4.00"><infProt><chNFe>{CHAVE}</chNFe><nProt>135260000012345</nProt>'
        "<cStat>100</cStat><xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe></retConsSitNFe>"
    )
    situacao = parse_consulta_situacao(xml)
    assert situacao.autorizado
    assert situacao.n_prot == "135260000012345"


def test_inutilizacao_homologada():
    xml = (
        f'<retInutNFe xmlns="{NFE}" versao="4.00"><infInut><tpAmb>2</tpAmb><cStat>102</cStat>'
        "<xMotivo>Inutilizacao de numero homologado</xMotivo><nProt>135260000000777</nProt></infInut></retInutNFe>"
    )
    retorno = parse_inutilizacao(xml)
    assert retorno.homologada
    assert retorno.n_prot == "135260000000777"


def test_retorno_invalido_nao_estoura():
    assert parse_autorizacao("isto não é xml").c_stat is None
    assert parse_evento(None).c_stat is None


def test_enderecos_nfce_e_nfe_de_sp_sao_distintos():
    nfce = get_sefaz_sp_nfce_config("homolog")
    nfe = get_sefaz_sp_wsdl_config("prod")
    assert nfce.autorizacao == "https://homologacao.nfce.fazenda.sp.gov.br/ws/NFeAutorizacao4.asmx"
    assert nfce.tp_amb == "2"
    assert nfe.autorizacao.startswith("https://nfe.fazenda.sp.gov.br/ws/nfeautorizacao4.asmx")
    assert nfe.tp_amb == "1"
    with pytest.raises(ValueError):
        get_sefaz_sp_nfce_config("teste")


def test_cliente_usa_endpoint_sem_wsdl_e_testa_status(monkeypatch):
    chamadas = []

    def fake_post(url, service, operation, body_xml, *, cert_files, timeout, session=None):
        chamadas.append((url, service, operation, body_xml))
        ret = f'<retConsStatServ xmlns="{NFE}" versao="4.00"><cStat>107</cStat><xMotivo>Servico em Operacao</xMotivo></retConsStatServ>'
        return sefaz_soap.SoapResult(True, 200, "<env/>", _envelope(service, ret), ret, None)

    monkeypatch.setattr("providers.nfe.sefaz_sp.client.post_soap12", fake_post)
    client = SefazSpNfeClient(get_sefaz_sp_wsdl_config("homolog"))
    response = client.test_connection("35")
    assert response.success
    url, service, operation, body = chamadas[0]
    assert url == "https://homologacao.nfe.fazenda.sp.gov.br/ws/nfestatusservico4.asmx"
    assert (service, operation) == ("NFeStatusServico4", "nfeStatusServicoNF")
    assert "<tpAmb>2</tpAmb>" in body and "<xServ>STATUS</xServ>" in body
