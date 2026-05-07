from lxml import etree

from providers.nfse.nacional.xml_builder import (
    NFSE_NS,
    build_cancel_event_xml,
    build_dps_id,
    build_dps_xml,
)


def test_build_dps_xml_para_bh_com_dados_do_pix():
    payload = {
        "municipio_ibge": "3106200",
        "data_competencia": "2026-05-05",
        "prestador": {
            "cnpj": "50.721.798/0001-39",
            "im": "123456",
            "nome": "RS SERVICOS VETERINARIOS",
            "regime_tributario": "simples_nacional",
        },
        "tomador": {
            "cpf_cnpj": "32.059.204/0001-94",
            "nome": "ANNATACHI BOTELHO JARDIM",
        },
        "servico": {
            "item_lista": "05.09",
            "cTribMun": "7500100",
            "cNBS": "114059000",
            "descricao": "Exames de ultrassonografia",
            "valor": "170.00",
            "aliquota_iss": "3.00",
        },
        "rps": {
            "numero": 1,
            "serie": "1",
            "data_emissao": "2026-05-06T12:00:00-03:00",
        },
    }

    xml = build_dps_xml(payload)
    root = etree.fromstring(xml.encode("utf-8"))
    ns = {"n": NFSE_NS}

    assert root.tag == f"{{{NFSE_NS}}}DPS"
    assert root.get("versao") == "1.01"
    assert root.findtext(".//n:cLocEmi", namespaces=ns) == "3106200"
    assert root.findtext(".//n:dCompet", namespaces=ns) == "2026-05-05"
    assert root.findtext(".//n:cTribNac", namespaces=ns) == "050900"
    assert root.findtext(".//n:cTribMun", namespaces=ns) == "7500100"
    assert root.findtext(".//n:cNBS", namespaces=ns) == "114059000"
    assert root.findtext(".//n:xDescServ", namespaces=ns) == "Exames de ultrassonografia"
    assert root.findtext(".//n:vServ", namespaces=ns) == "170.00"
    assert root.findtext(".//n:opSimpNac", namespaces=ns) == "3"
    assert root.findtext(".//n:regApTribSN", namespaces=ns) == "1"

    inf = root.find(".//n:infDPS", namespaces=ns)
    assert inf is not None
    assert inf.get("Id") == build_dps_id("3106200", "50721798000139", "1", "1")
    assert len(inf.get("Id")) == 45


def test_build_cancel_event_xml():
    chave = "1" * 50

    xml = build_cancel_event_xml(
        chave,
        "50.721.798/0001-39",
        reason_code="1",
        reason_description="Erro na emissao",
        event_datetime="2026-05-06T12:00:00-03:00",
    )
    root = etree.fromstring(xml.encode("utf-8"))
    ns = {"n": NFSE_NS}
    inf = root.find(".//n:infPedReg", namespaces=ns)

    assert root.tag == f"{{{NFSE_NS}}}pedRegEvento"
    assert inf is not None
    assert inf.get("Id") == f"PRE{chave}101101001"
    assert root.findtext(".//n:CNPJAutor", namespaces=ns) == "50721798000139"
    assert root.findtext(".//n:e101101/n:xDesc", namespaces=ns) == "Cancelamento de NFS-e"
    assert root.findtext(".//n:e101101/n:cMotivo", namespaces=ns) == "1"
