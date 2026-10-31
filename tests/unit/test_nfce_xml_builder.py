"""XML da NFC-e conferido contra o esquema oficial e as regras da SEFAZ."""
from __future__ import annotations

import base64
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from providers.nfce.qrcode import (
    URLS_SP,
    parametros_v3_offline,
    qrcode_v2_online,
    qrcode_v3_offline,
    qrcode_v3_online,
)
from providers.nfce.xml_builder import (
    HOMOLOG_DEST,
    HOMOLOG_ITEM,
    EmitenteNfce,
    ItemNfce,
    NfceDados,
    NfceValidationError,
    PagamentoNfce,
    build_nfce_xml,
    gtin_valido,
)
from providers.nfe.chave import montar_chave
from providers.nfe.xml_builder import build_envi_nfe_xml
from providers.nfe.xml_signer import sign_nfe_xml


NFE = "http://www.portalfiscal.inf.br/nfe"
XSD_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "nfe_xsd_v4"
DH_EMI = "2026-10-31T10:15:00-03:00"


@pytest.fixture(scope="module")
def schemas():
    return {
        "nfe": etree.XMLSchema(etree.parse(str(XSD_DIR / "nfe_v4.00.xsd"))),
        "lote": etree.XMLSchema(etree.parse(str(XSD_DIR / "enviNFe_v4.00.xsd"))),
    }


@pytest.fixture(scope="module")
def a1():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CAT DOG PET SHOP:12345678000195")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(11).not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=60)).sign(key, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(b"a1", key, cert, None, serialization.BestAvailableEncryption(b"x"))
    return {"key": key, "cert": cert, "pfx": pfx, "password": "x"}


def _emitente() -> EmitenteNfce:
    return EmitenteNfce(
        cnpj="12.345.678/0001-95",
        razao_social="Cat Dog Pet Shop Ltda",
        nome_fantasia="Cat Dog",
        ie="481.234.567.110",
        logradouro="Rua Oito",
        numero="2054A",
        bairro="Jardim Santa Rita",
        codigo_municipio="3534302",
        municipio="Orlandia",
        cep="14620-000",
        telefone="(16) 99858-0506",
    )


def _dados(tp_amb="1", itens=None, pagamentos=None, cpf=None, tp_emis="1", **extra) -> NfceDados:
    chave = montar_chave(
        c_uf="35", dh_emi=DH_EMI, cnpj="12345678000195", modelo="65", serie=1, numero=123, tp_emis=tp_emis
    )
    itens = itens or [
        ItemNfce(
            codigo="RAC-15",
            descricao="Ração Special Dog Ultralife 15kg",
            ncm="2309.10.00",
            quantidade=Decimal("1"),
            valor_unitario=Decimal("189.90"),
            gtin="7891000315507",
            cest="2299900",
        ),
        ItemNfce(
            codigo="GRANEL",
            descricao="Ração a granel (kg)",
            ncm="23091000",
            quantidade=Decimal("1.255"),
            valor_unitario=Decimal("12.90"),
            unidade="KG",
            desconto=Decimal("0.19"),
            csosn="500",
        ),
    ]
    pagamentos = pagamentos or [PagamentoNfce(t_pag="01", valor=Decimal("210.00"))]
    return NfceDados(
        emitente=_emitente(),
        itens=itens,
        pagamentos=pagamentos,
        chave=chave,
        serie=1,
        numero=123,
        dh_emi=DH_EMI,
        tp_amb=tp_amb,
        tp_emis=tp_emis,
        cpf_consumidor=cpf,
        **extra,
    )


def _build_signed(dados: NfceDados, a1) -> str:
    urls = URLS_SP[dados.tp_amb]
    qr = qrcode_v3_online(urls["qrcode"], dados.chave.chave, dados.tp_amb)
    xml = build_nfce_xml(dados, qrcode=qr, url_chave=urls["chave"])
    return sign_nfe_xml(xml, a1["pfx"], a1["password"])


def _assert_schema(schema, xml: str) -> etree._Element:
    root = etree.fromstring(xml.encode("utf-8"))
    if not schema.validate(root):
        erros = "\n".join(str(e) for e in schema.error_log)
        pytest.fail(f"XML fora do esquema oficial:\n{erros}")
    return root


def test_nfce_assinada_valida_no_esquema_oficial(a1, schemas):
    signed = _build_signed(_dados(), a1)
    root = _assert_schema(schemas["nfe"], signed)
    assert [etree.QName(c).localname for c in root] == ["infNFe", "infNFeSupl", "Signature"]
    lote = build_envi_nfe_xml(signed, id_lote=1)
    _assert_schema(schemas["lote"], lote)


def test_valores_e_totais_batem_com_os_itens(a1):
    root = etree.fromstring(_build_signed(_dados(), a1).encode("utf-8"))
    ns = {"n": NFE}
    v_prods = [Decimal(x.text) for x in root.findall(".//n:det/n:prod/n:vProd", ns)]
    # 1,255 kg × 12,90 = 16,1895 -> 16,19 (arredondamento a 2 casas)
    assert v_prods == [Decimal("189.90"), Decimal("16.19")]
    assert root.find(".//n:ICMSTot/n:vProd", ns).text == "206.09"
    assert root.find(".//n:ICMSTot/n:vDesc", ns).text == "0.19"
    assert root.find(".//n:ICMSTot/n:vNF", ns).text == "205.90"
    assert root.find(".//n:ICMSTot/n:vBC", ns).text == "0.00"
    assert root.find(".//n:pag/n:vTroco", ns).text == "4.10"
    qcom = root.findall(".//n:det/n:prod/n:qCom", ns)
    assert qcom[1].text == "1.2550"
    assert root.find(".//n:det[@nItem='2']//n:ICMSSN500/n:CSOSN", ns).text == "500"
    assert root.find(".//n:det[@nItem='2']/n:prod/n:CFOP", ns).text == "5405"
    assert root.find(".//n:det[@nItem='1']/n:prod/n:CFOP", ns).text == "5102"
    assert root.find(".//n:det[@nItem='1']/n:prod/n:cEAN", ns).text == "7891000315507"
    assert root.find(".//n:det[@nItem='2']/n:prod/n:cEAN", ns).text == "SEM GTIN"
    assert root.find(".//n:ide/n:tpImp", ns).text == "4"
    assert root.find(".//n:ide/n:mod", ns).text == "65"


def test_homologacao_troca_descricao_do_primeiro_item_e_nome(a1, schemas):
    dados = _dados(tp_amb="2", cpf="123.456.789-09", nome_consumidor="Fulano")
    signed = _build_signed(dados, a1)
    root = _assert_schema(schemas["nfe"], signed)
    ns = {"n": NFE}
    assert root.find(".//n:det[@nItem='1']/n:prod/n:xProd", ns).text == HOMOLOG_ITEM
    assert root.find(".//n:det[@nItem='2']/n:prod/n:xProd", ns).text == "Ração a granel (kg)"
    assert root.find(".//n:dest/n:xNome", ns).text == HOMOLOG_DEST
    assert root.find(".//n:dest/n:CPF", ns).text == "12345678909"
    assert "homologacao" in root.find(".//n:infNFeSupl/n:qrCode", ns).text


def test_cartao_e_pix_levam_grupo_card(a1, schemas):
    pagamentos = [
        PagamentoNfce(t_pag="03", valor=Decimal("100.00"), cnpj_credenciadora="01.027.058/0001-91", autorizacao="A1B2"),
        PagamentoNfce(t_pag="17", valor=Decimal("50.00")),
        PagamentoNfce(t_pag="20", valor=Decimal("55.90")),
    ]
    signed = _build_signed(_dados(pagamentos=pagamentos), a1)
    root = _assert_schema(schemas["nfe"], signed)
    ns = {"n": NFE}
    det_pags = root.findall(".//n:pag/n:detPag", ns)
    assert [d.find("n:tPag", ns).text for d in det_pags] == ["03", "17", "20"]
    assert det_pags[0].find("n:card/n:tpIntegra", ns).text == "2"
    assert det_pags[0].find("n:card/n:CNPJ", ns).text == "01027058000191"
    assert det_pags[0].find("n:card/n:cAut", ns).text == "A1B2"
    assert det_pags[1].find("n:card/n:tpIntegra", ns).text == "2"
    assert det_pags[2].find("n:card", ns) is None
    assert root.find(".//n:pag/n:vTroco", ns) is None


def test_tributos_aproximados(a1, schemas):
    signed = _build_signed(_dados(percentual_tributos=Decimal("12.50"), inf_cpl="Obrigado pela preferência!"), a1)
    root = _assert_schema(schemas["nfe"], signed)
    ns = {"n": NFE}
    assert root.find(".//n:ICMSTot/n:vTotTrib", ns).text == "25.74"
    inf_cpl = root.find(".//n:infAdic/n:infCpl", ns).text
    assert "R$ 25,74" in inf_cpl and "Obrigado" in inf_cpl


def test_contingencia_offline_valida_no_esquema(a1, schemas):
    dados = _dados(tp_emis="9", dh_cont=DH_EMI, x_just="Sem comunicacao com a SEFAZ no momento da venda")
    urls = URLS_SP["1"]
    qr = qrcode_v3_offline(
        urls["qrcode"], dados.chave.chave, "1", DH_EMI, dados.total_nota, a1["key"]
    )
    xml = build_nfce_xml(dados, qrcode=qr, url_chave=urls["chave"])
    root = _assert_schema(schemas["nfe"], sign_nfe_xml(xml, a1["pfx"], a1["password"]))
    ns = {"n": NFE}
    assert root.find(".//n:ide/n:tpEmis", ns).text == "9"
    assert dados.chave.tp_emis == "9"


def test_qrcode_v3_offline_assinatura_confere(a1):
    chave = montar_chave(c_uf="35", dh_emi=DH_EMI, cnpj="12345678000195", modelo="65", serie=1, numero=5, tp_emis="9").chave
    url = qrcode_v3_offline("https://x/qrcode", chave, "2", DH_EMI, Decimal("15.5"), a1["key"], "2", "12345678909")
    params = url.split("?p=", 1)[1].split("|")
    assert params[:7] == [chave, "3", "2", "31", "15.50", "2", "12345678909"]
    base = parametros_v3_offline(chave, "2", DH_EMI, Decimal("15.5"), "2", "12345678909")
    a1["cert"].public_key().verify(base64.b64decode(params[7]), base.encode(), padding.PKCS1v15(), hashes.SHA1())


def test_qrcode_v3_offline_sem_consumidor_mantem_separadores():
    base = parametros_v3_offline("1" * 44, "1", DH_EMI, Decimal("10"))
    assert base == f"{'1' * 44}|3|1|31|10.00||"


def test_qrcode_v2_online_com_csc():
    url = qrcode_v2_online("https://x/qrcode", "3" * 44, "2", "000001", "CSC-TESTE")
    p = url.split("?p=", 1)[1]
    parts = p.split("|")
    assert parts[:4] == ["3" * 44, "2", "2", "1"]
    assert len(parts[4]) == 40 and parts[4] == parts[4].upper()


def test_qrcode_v3_online():
    assert qrcode_v3_online("https://x/q", "4" * 44, "1") == f"https://x/q?p={'4' * 44}|3|1"


@pytest.mark.parametrize(
    "codigo,esperado",
    [
        ("7891000315507", True),
        ("7891000315508", False),
        ("2000001000014", False),
        ("12345670", True),
        ("SEM GTIN", False),
        (None, False),
        ("789100031550", False),
    ],
)
def test_gtin_valido(codigo, esperado):
    assert gtin_valido(codigo) is esperado


def test_validacoes_antes_de_enviar():
    with pytest.raises(NfceValidationError, match="NCM"):
        build_nfce_xml(
            _dados(itens=[ItemNfce(codigo="1", descricao="Sem NCM", ncm="", quantidade=Decimal(1), valor_unitario=Decimal(5))],
                   pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal(5))]),
            qrcode="https://x/q?p=1",
            url_chave="https://x/consulta",
        )
    with pytest.raises(NfceValidationError, match="menor que o total"):
        build_nfce_xml(_dados(pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal("1.00"))]), qrcode="q", url_chave="u")
    with pytest.raises(NfceValidationError, match="troco"):
        build_nfce_xml(_dados(pagamentos=[PagamentoNfce(t_pag="03", valor=Decimal("300.00"))]), qrcode="q", url_chave="u")
    with pytest.raises(NfceValidationError, match="CPF"):
        build_nfce_xml(_dados(cpf="123"), qrcode="q", url_chave="u")
