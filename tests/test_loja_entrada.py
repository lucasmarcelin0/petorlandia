"""Entrada de mercadoria pelo XML da NF-e de compra: leitura, sugestões,
conferência, lançamento no estoque, estorno e telas."""
from __future__ import annotations

from decimal import Decimal
import io
import zipfile

import flask_login.utils as login_utils
import pytest

from extensions import db
from models import (
    CasaDeRacao,
    EstoqueMovimento,
    LojaEntradaNota,
    LojaFornecedorProduto,
    Product,
    ProductVariant,
    User,
)
from providers.nfe.leitor_compra import NotaCompraInvalida, ler_nota_compra
from services.loja_caixa import entrada as entrada_service
from services.loja_caixa import estoque
from services.loja_caixa.entrada import EntradaError

NFE = "http://www.portalfiscal.inf.br/nfe"
CNPJ_LOJA = "12345678000195"
CNPJ_FORNECEDOR = "11222333000181"
GTIN_RACAO = "7891000315507"
GTIN_SACHE_UN = "7896181212348"


def _det(n, codigo, nome, ncm, ucom, qcom, vun, vprod, cean="SEM GTIN", utrib=None, qtrib=None, cean_trib=None,
         frete="0.00", st=None):
    utrib = utrib or ucom
    qtrib = qtrib or qcom
    cean_trib = cean_trib or cean
    frete_xml = f"<vFrete>{frete}</vFrete>" if frete != "0.00" else ""
    if st:
        icms = f"<ICMS10><orig>0</orig><CST>10</CST><vICMSST>{st}</vICMSST></ICMS10>"
    else:
        icms = "<ICMSSN102><orig>0</orig><CSOSN>102</CSOSN></ICMSSN102>"
    return (
        f'<det nItem="{n}"><prod><cProd>{codigo}</cProd><cEAN>{cean}</cEAN><xProd>{nome}</xProd><NCM>{ncm}</NCM>'
        f"<CFOP>5102</CFOP><uCom>{ucom}</uCom><qCom>{qcom}</qCom><vUnCom>{vun}</vUnCom><vProd>{vprod}</vProd>"
        f"<cEANTrib>{cean_trib}</cEANTrib><uTrib>{utrib}</uTrib><qTrib>{qtrib}</qTrib><vUnTrib>{vun}</vUnTrib>"
        f"{frete_xml}<indTot>1</indTot></prod><imposto><ICMS>{icms}</ICMS></imposto></det>"
    )


def _nota(numero="1234", dets=None, dest=CNPJ_LOJA, autorizada=True, chave_final="1") -> bytes:
    chave = f"3526101122233300018155001{int(numero):09d}1123456789"[:43] + chave_final
    dets = dets or [
        _det(1, "RAC15", "RACAO PREMIUM ADULTO 15KG", "23091000", "UN", "2.0000", "120.00", "240.00",
             cean=GTIN_RACAO, frete="10.00", st="5.00"),
        _det(2, "SACH12", "SACHE GATO CX 12UN", "23091000", "CX", "2.0000", "24.00", "48.00",
             utrib="UN", qtrib="24.0000", cean_trib=GTIN_SACHE_UN),
        _det(3, "BRINQ", "BRINQUEDO MORDEDOR", "95030099", "UN", "3.0000", "10.00", "30.00"),
    ]
    prot = (
        f'<protNFe versao="4.00"><infProt><chNFe>{chave}</chNFe><nProt>135260000001111</nProt>'
        "<cStat>100</cStat><xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe>"
        if autorizada else ""
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><nfeProc xmlns="{NFE}" versao="4.00"><NFe>'
        f'<infNFe Id="NFe{chave}" versao="4.00"><ide><cUF>35</cUF><mod>55</mod><serie>1</serie><nNF>{numero}</nNF>'
        "<dhEmi>2026-10-20T10:00:00-03:00</dhEmi></ide>"
        f"<emit><CNPJ>{CNPJ_FORNECEDOR}</CNPJ><xNome>DISTRIBUIDORA PET LTDA</xNome><xFant>Distribuidora Pet</xFant></emit>"
        f"<dest><CNPJ>{dest}</CNPJ><xNome>CAT DOG</xNome></dest>"
        + "".join(dets)
        + "<total><ICMSTot><vNF>333.00</vNF></ICMSTot></total></infNFe></NFe>"
        + prot
        + "</nfeProc>"
    ).encode("utf-8")


@pytest.fixture()
def loja(app):
    owner = User(name="Renato", email="renato-entrada@example.com")
    owner.set_password("x")
    outro = User(name="Outro", email="outro-entrada@example.com")
    outro.set_password("x")
    db.session.add_all([owner, outro])
    db.session.flush()
    casa = CasaDeRacao(nome="Cat Dog", owner_id=owner.id, status="ativa", cnpj=CNPJ_LOJA)
    db.session.add(casa)
    db.session.flush()
    racao = Product(name="Ração Premium 15kg", price=189.9, stock=3, casa_de_racao_id=casa.id)
    racao.variants.append(ProductVariant(name="15 kg", price=189.9, stock=3, barcode=GTIN_RACAO, status="active"))
    db.session.add(racao)
    db.session.commit()
    return {"casa": casa, "owner": owner, "outro": outro, "racao": racao}


def _itens(entrada):
    return {item.codigo_fornecedor: item for item in entrada.itens}


# ----------------------------------------------------------------- leitura

def test_le_a_nota_de_compra():
    nota = ler_nota_compra(_nota())
    assert nota.numero == "1234" and nota.fornecedor_cnpj == CNPJ_FORNECEDOR
    assert nota.fornecedor_nome == "Distribuidora Pet"
    assert nota.destinatario_documento == CNPJ_LOJA
    assert nota.autorizada and nota.protocolo == "135260000001111"
    racao, sache, brinquedo = nota.itens
    assert racao.gtin == GTIN_RACAO
    assert racao.custo_total == Decimal("255.00")  # 240 + frete 10 + ST 5
    assert sache.gtin is None and sache.gtin_trib == GTIN_SACHE_UN
    assert sache.fator_sugerido == Decimal("12")
    assert brinquedo.fator_sugerido == Decimal("1")


@pytest.mark.parametrize(
    "conteudo, mensagem",
    [
        (b"nao sou xml", "não é um XML"),
        (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>', "Não foi possível ler"),
        (b'<pedido xmlns="http://www.portalfiscal.inf.br/nfe"/>', "não é uma NF-e"),
        (_nota().replace(b"<mod>55</mod>", b"<mod>65</mod>"), "modelo 55"),
    ],
)
def test_arquivo_que_nao_e_nota_de_compra(conteudo, mensagem):
    with pytest.raises(NotaCompraInvalida, match=mensagem):
        ler_nota_compra(conteudo)


# ------------------------------------------------------------ importação

def test_importa_com_sugestoes(loja):
    entrada = entrada_service.importar_xml(loja["casa"], _nota(), usuario_id=loja["owner"].id)
    assert entrada.status == "rascunho" and entrada.autorizada
    itens = _itens(entrada)
    racao = itens["RAC15"]
    assert racao.acao == "vincular" and racao.sugestao == "codigo_barras"
    assert racao.product_id == loja["racao"].id
    assert racao.custo_unitario == Decimal("127.5000")
    sache = itens["SACH12"]
    assert sache.acao == "criar" and sache.fator == Decimal("12") and sache.unidade_venda == "UN"
    assert sache.quantidade_estoque == Decimal("24")
    assert sache.custo_unitario == Decimal("2.0000")
    assert sache.preco_venda == Decimal("3.00")  # custo + 50%
    brinquedo = itens["BRINQ"]
    assert brinquedo.acao == "criar" and brinquedo.preco_venda == Decimal("15.00")
    # Nada mexe no estoque antes de lançar.
    assert EstoqueMovimento.query.count() == 0


def test_recusa_nota_repetida_e_de_outro_cnpj(loja):
    entrada_service.importar_xml(loja["casa"], _nota())
    with pytest.raises(EntradaError, match="já foi importada"):
        entrada_service.importar_xml(loja["casa"], _nota())
    with pytest.raises(EntradaError, match="outro CNPJ"):
        entrada_service.importar_xml(loja["casa"], _nota(numero="99", dest="99888777000166"))


# ------------------------------------------------------------- lançamento

def test_lancar_soma_estoque_cria_produtos_e_grava_vinculos(loja):
    casa = loja["casa"]
    entrada = entrada_service.importar_xml(casa, _nota())
    entrada_service.lancar_entrada(entrada, usuario_id=loja["owner"].id)
    assert entrada.status == "lancada"

    variante_racao = loja["racao"].variants[0]
    assert variante_racao.stock == 5 and loja["racao"].stock == 5
    assert variante_racao.custo == Decimal("127.5000")
    assert loja["racao"].ncm == "23091000"  # completou o cadastro fiscal

    sache = Product.query.filter_by(name="SACHE GATO CX 12UN").one()
    assert sache.status == "inactive", "produto novo entra fora da loja online"
    assert sache.casa_de_racao_id == casa.id and sache.ncm == "23091000"
    assert sache.variants[0].barcode == GTIN_SACHE_UN
    assert sache.variants[0].stock == 24 and sache.price == 3.0

    movimentos = EstoqueMovimento.query.filter_by(tipo="entrada_nota").all()
    assert len(movimentos) == 3
    assert {m.custo_unitario for m in movimentos} == {Decimal("127.5"), Decimal("2"), Decimal("10")}
    assert LojaFornecedorProduto.query.count() == 3

    # Próxima nota do mesmo fornecedor: tudo já vem vinculado.
    segunda = entrada_service.importar_xml(casa, _nota(numero="1235"))
    itens = _itens(segunda)
    assert all(item.acao == "vincular" for item in itens.values())
    assert itens["SACH12"].sugestao == "fornecedor" and itens["SACH12"].fator == Decimal("12")
    assert itens["SACH12"].product_id == sache.id


def test_conferencia_ignora_vincula_e_valida(loja):
    casa = loja["casa"]
    entrada = entrada_service.importar_xml(casa, _nota())
    itens = _itens(entrada)
    dados = {
        f"item_{itens['BRINQ'].id}_acao": "ignorar",
        f"item_{itens['SACH12'].id}_acao": "criar",
        f"item_{itens['SACH12'].id}_fator": "5",  # 2 CX x 5 = 10
        f"item_{itens['SACH12'].id}_preco_venda": "4,50",
        f"item_{itens['SACH12'].id}_nome": "Sachê Gato Sabor Carne",
    }
    entrada_service.salvar_conferencia(entrada, dados)
    assert itens["BRINQ"].acao == "ignorar"
    assert itens["SACH12"].preco_venda == Decimal("4.50")

    # Fator que não fecha unidade inteira é recusado antes de mexer no estoque.
    entrada_service.salvar_conferencia(entrada, {f"item_{itens['SACH12'].id}_fator": "2,25"})
    with pytest.raises(EntradaError, match="não fecha um número inteiro"):
        entrada_service.lancar_entrada(entrada)
    assert EstoqueMovimento.query.count() == 0

    entrada_service.salvar_conferencia(entrada, {f"item_{itens['SACH12'].id}_fator": "5"})
    entrada_service.lancar_entrada(entrada)
    sache = Product.query.filter_by(name="Sachê Gato Sabor Carne").one()
    assert sache.variants[0].stock == 10 and sache.price == 4.5
    assert Product.query.filter_by(name="BRINQUEDO MORDEDOR").count() == 0


def test_vincular_exige_produto_da_propria_loja(loja):
    casa = loja["casa"]
    outra = CasaDeRacao(nome="Outra", owner_id=loja["outro"].id, status="ativa")
    db.session.add(outra)
    db.session.flush()
    alheio = Product(name="Alheio", price=1.0, stock=0, casa_de_racao_id=outra.id)
    db.session.add(alheio)
    db.session.commit()
    entrada = entrada_service.importar_xml(casa, _nota())
    brinquedo = _itens(entrada)["BRINQ"]
    entrada_service.salvar_conferencia(
        entrada, {f"item_{brinquedo.id}_acao": "vincular", f"item_{brinquedo.id}_product_id": str(alheio.id)}
    )
    with pytest.raises(EntradaError, match="escolha o produto"):
        entrada_service.lancar_entrada(entrada)
    assert alheio.stock == 0


def test_estorno_devolve_o_estoque(loja):
    entrada = entrada_service.importar_xml(loja["casa"], _nota())
    entrada_service.lancar_entrada(entrada)
    entrada_service.estornar_entrada(entrada)
    assert entrada.status == "estornada"
    assert loja["racao"].variants[0].stock == 3
    with pytest.raises(EntradaError):
        entrada_service.estornar_entrada(entrada)


def test_granel_em_kg_aceita_fracao(loja):
    casa = loja["casa"]
    granel = Product(name="Ração a granel", price=12.0, stock=0, casa_de_racao_id=casa.id, unidade="KG")
    granel.variants.append(ProductVariant(name="Granel", price=12.0, stock=0, status="active"))
    db.session.add(granel)
    db.session.commit()
    nota = _nota(dets=[_det(1, "GRANEL", "RACAO SACO 15KG", "23091000", "SC", "1.0000", "150.00", "150.00")])
    entrada = entrada_service.importar_xml(casa, nota)
    item = entrada.itens[0]
    entrada_service.salvar_conferencia(
        entrada,
        {
            f"item_{item.id}_acao": "vincular",
            f"item_{item.id}_product_id": str(granel.id),
            f"item_{item.id}_variant_id": str(granel.variants[0].id),
            f"item_{item.id}_fator": "15,5",
        },
    )
    entrada_service.lancar_entrada(entrada)
    assert estoque.saldo(granel, granel.variants[0]) == Decimal("15.5")


# ------------------------------------------------------------------- telas

def test_telas_de_entrada(loja, client, monkeypatch):
    monkeypatch.setattr(login_utils, "_get_user", lambda: loja["owner"])
    casa_id = loja["casa"].id
    assert client.get(f"/casa-de-racao/{casa_id}/estoque/entradas").status_code == 200

    resposta = client.post(
        f"/casa-de-racao/{casa_id}/estoque/entradas/importar",
        data={"arquivos": (io.BytesIO(_nota()), "nota.xml")},
        content_type="multipart/form-data",
    )
    entrada = LojaEntradaNota.query.one()
    assert resposta.status_code == 302 and resposta.headers["Location"].endswith(f"/entradas/{entrada.id}")
    pagina = client.get(f"/casa-de-racao/{casa_id}/estoque/entradas/{entrada.id}").get_data(as_text=True)
    assert "RACAO PREMIUM ADULTO 15KG" in pagina and "pelo código de barras" in pagina

    itens = _itens(entrada)
    resposta = client.post(
        f"/casa-de-racao/{casa_id}/estoque/entradas/{entrada.id}",
        data={
            "acao_tela": "lancar",
            f"item_{itens['BRINQ'].id}_acao": "criar",
            f"item_{itens['BRINQ'].id}_preco_venda": "19,90",
        },
    )
    assert resposta.status_code == 302
    db.session.refresh(entrada)
    assert entrada.status == "lancada"
    assert Product.query.filter_by(name="BRINQUEDO MORDEDOR").one().price == 19.9

    xml = client.get(f"/casa-de-racao/{casa_id}/estoque/entradas/{entrada.id}/xml")
    assert xml.status_code == 200 and b"<nfeProc" in xml.data

    # .zip com duas notas novas e uma repetida
    pacote = io.BytesIO()
    with zipfile.ZipFile(pacote, "w") as zf:
        zf.writestr("a.xml", _nota(numero="2001"))
        zf.writestr("b.xml", _nota(numero="2002"))
        zf.writestr("c.xml", _nota())
    pacote.seek(0)
    resposta = client.post(
        f"/casa-de-racao/{casa_id}/estoque/entradas/importar",
        data={"arquivos": (pacote, "notas.zip")},
        content_type="multipart/form-data",
    )
    assert resposta.status_code == 302
    assert LojaEntradaNota.query.count() == 3

    rascunho = LojaEntradaNota.query.filter_by(numero="2002").one()
    assert client.post(f"/casa-de-racao/{casa_id}/estoque/entradas/{rascunho.id}/excluir").status_code == 302
    assert LojaEntradaNota.query.count() == 2
    assert client.post(f"/casa-de-racao/{casa_id}/estoque/entradas/{entrada.id}/estornar").status_code == 302
    db.session.refresh(entrada)
    assert entrada.status == "estornada"


def test_outra_loja_nao_ve_as_entradas(loja, client, monkeypatch):
    entrada = entrada_service.importar_xml(loja["casa"], _nota())
    monkeypatch.setattr(login_utils, "_get_user", lambda: loja["outro"])
    casa_id = loja["casa"].id
    assert client.get(f"/casa-de-racao/{casa_id}/estoque/entradas").status_code == 404
    assert client.get(f"/casa-de-racao/{casa_id}/estoque/entradas/{entrada.id}").status_code == 404
    assert client.get(f"/casa-de-racao/{casa_id}/estoque/entradas/{entrada.id}/xml").status_code == 404
