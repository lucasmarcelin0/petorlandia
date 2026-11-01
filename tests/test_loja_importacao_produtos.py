"""Importação do catálogo da loja por planilha CSV (migração de outro sistema)."""
from __future__ import annotations

from decimal import Decimal
import gzip
import html
import io
import random
import re

import flask_login.utils as login_utils
import pytest

from extensions import db
from models import CasaDeRacao, EstoqueMovimento, Product, ProductVariant, User
from services.loja_caixa import importacao_produtos as importacao
from services.loja_caixa.importacao_produtos import PlanilhaInvalida

GTIN = "7891000315507"


@pytest.fixture()
def loja(app):
    owner = User(name="Renato", email="renato-import@example.com")
    owner.set_password("x")
    outro = User(name="Outro", email="outro-import@example.com")
    outro.set_password("x")
    db.session.add_all([owner, outro])
    db.session.flush()
    casa = CasaDeRacao(nome="Cat Dog", owner_id=owner.id, status="ativa")
    db.session.add(casa)
    db.session.flush()
    racao = Product(name="Ração Premium 15kg", price=189.9, stock=3, casa_de_racao_id=casa.id, ncm="23091000")
    racao.variants.append(ProductVariant(name="15 kg", price=189.9, stock=3, barcode=GTIN, status="active"))
    coleira = Product(name="Coleira P", price=30.0, stock=1, casa_de_racao_id=casa.id)
    coleira.variants.append(ProductVariant(name="P", price=30.0, stock=1, sku="COL-P", status="active"))
    db.session.add_all([racao, coleira])
    db.session.commit()
    return {"casa": casa, "owner": owner, "outro": outro, "racao": racao, "coleira": coleira}


def _csv(*linhas: str, codificacao: str = "utf-8") -> bytes:
    return ("\n".join(linhas) + "\n").encode(codificacao)


PLANILHA_ORLASOFT = _csv(
    "Código de Barras;Código;Descrição;Preço de Venda;Custo;Unidade;Estoque;NCM;CFOP;CSOSN;Origem",
    f"{GTIN};RAC15;Ração Premium 15kg;199,90;120,00;UN;8;23091000;5102;102;0",
    ";COL-P;Coleira P;35,00;12,50;UND;4;42010090;5102;102;0",
    "7896181212348.0;SACH;Sachê Gato Carne 85g;4,50;2,10;UN;24;23091000;5102;102;0",
    ";GRANEL;Ração a granel gato;18,50;11,20;KG;12,5;23091000;5102;102;0",
    ";;Brinquedo sem preço;;;UN;3;;;;",
    "7,89E+12;;Arranhador;89,90;;UN;1,5;9999;5102;102;0",
    codificacao="cp1252",
)


def _previa(pagina: str) -> str:
    return html.unescape(re.search(r'name="previa" value="([^"]*)"', pagina).group(1))


def test_le_csv_do_excel_com_titulos_comuns():
    linhas = importacao.ler_planilha(PLANILHA_ORLASOFT)
    assert len(linhas) == 6
    assert linhas[0]["codigo_barras"] == GTIN and linhas[0]["nome"] == "Ração Premium 15kg"
    assert linhas[0]["preco"] == "199,90" and linhas[0]["linha"] == "2"


@pytest.mark.parametrize(
    "conteudo, mensagem",
    [
        (b"", "vazio"),
        (b"PK\x03\x04qualquer", "Excel"),
        (_csv("codigo;preco", "1;2"), "nome do produto"),
        (_csv("nome;preco"), "não tem linhas"),
    ],
)
def test_planilha_invalida(conteudo, mensagem):
    with pytest.raises(PlanilhaInvalida, match=mensagem):
        importacao.ler_planilha(conteudo)


def test_previa_reconhece_existentes_e_aponta_erros(loja):
    plano = importacao.planejar(loja["casa"].id, importacao.ler_planilha(PLANILHA_ORLASOFT))
    por_linha = {linha.numero: linha for linha in plano}

    racao = por_linha[2]
    assert racao.acao == "atualizar" and racao.product.id == loja["racao"].id  # pelo código de barras
    assert "CFOP 5102" in racao.mudancas and "código RAC15" in racao.mudancas
    assert not any(m.startswith(("NCM", "preço", "estoque")) for m in racao.mudancas), "o que já existe fica"
    coleira = por_linha[3]
    assert coleira.acao == "atualizar" and coleira.product.id == loja["coleira"].id  # pelo código interno
    assert any("NCM 42010090" in m for m in coleira.mudancas) and any("custo" in m for m in coleira.mudancas)
    assert not any("preço" in m for m in coleira.mudancas), "preço só muda com a opção marcada"

    sache = por_linha[4]
    assert sache.acao == "criar" and sache.codigo_barras == "7896181212348"  # o ".0" do Excel sai
    assert por_linha[5].acao == "criar" and por_linha[5].unidade == "KG"
    assert por_linha[6].acao == "erro" and "sem preço" in por_linha[6].erros
    arranhador = por_linha[7]
    assert arranhador.acao == "criar" and arranhador.codigo_barras is None
    assert any("arredondado para baixo" in a for a in arranhador.avisos)
    assert any("notação científica" in a for a in arranhador.avisos)
    assert any("NCM inválido" in a for a in arranhador.avisos)
    assert importacao.resumo(plano) == {"linhas": 6, "criar": 3, "atualizar": 2, "nada": 0, "erro": 1}


def test_repetido_na_planilha_e_nome_ambiguo(loja):
    db.session.add(Product(name="Coleira P", price=31.0, stock=0, casa_de_racao_id=loja["casa"].id))
    db.session.commit()
    linhas = importacao.ler_planilha(_csv(
        "codigo_barras;nome;preco",
        "7896181212348;Sachê;4,50",
        "7896181212348;Sachê de novo;4,50",
        ";Coleira P;35",
    ))
    plano = importacao.planejar(loja["casa"].id, linhas)
    assert plano[1].acao == "erro" and "repetido na planilha (linha 2)" in plano[1].erros[0]
    assert plano[2].acao == "erro" and "mais de um produto com este nome" in plano[2].erros[0]


def test_grava_novos_completa_existentes_e_registra_estoque(loja):
    totais = importacao.aplicar(loja["casa"], importacao.ler_planilha(PLANILHA_ORLASOFT), usuario_id=loja["owner"].id)
    assert totais == {"criados": 3, "atualizados": 2, "sem_mudanca": 0, "com_erro": 1, "com_estoque": 3}
    # Importar a mesma planilha de novo não muda nada.
    de_novo = importacao.resumo(importacao.planejar(loja["casa"].id, importacao.ler_planilha(PLANILHA_ORLASOFT)))
    assert de_novo == {"linhas": 6, "criar": 0, "atualizar": 0, "nada": 5, "erro": 1}

    sache = Product.query.filter_by(name="Sachê Gato Carne 85g").one()
    variante = sache.variants[0]
    assert sache.status == "inactive", "entra fora da loja online"
    assert sache.price == 4.5 and sache.ncm == "23091000" and sache.csosn == "102" and sache.cfop == "5102"
    assert variante.barcode == "7896181212348" and variante.sku == "SACH" and variante.custo == Decimal("2.1")
    assert variante.stock == 24 and sache.stock == 24
    movimento = EstoqueMovimento.query.filter_by(product_id=sache.id).one()
    assert movimento.tipo == "inventario" and movimento.quantidade == Decimal("24")

    granel = Product.query.filter_by(name="Ração a granel gato").one()
    assert granel.unidade == "KG" and granel.variants[0].stock == 12  # coluna inteira
    assert EstoqueMovimento.query.filter_by(product_id=granel.id).one().saldo_apos == Decimal("12.5")

    arranhador = Product.query.filter_by(name="Arranhador").one()
    assert arranhador.variants[0].stock == 1 and arranhador.ncm is None  # 1,5 em UN arredonda para 1

    coleira = loja["coleira"]
    assert coleira.ncm == "42010090" and coleira.variants[0].custo == Decimal("12.5")
    assert coleira.price == 30.0 and coleira.variants[0].stock == 1, "preço e estoque ficaram como estavam"
    assert loja["racao"].price == 189.9 and loja["racao"].variants[0].stock == 3
    assert Product.query.filter_by(name="Brinquedo sem preço").count() == 0


def test_opcoes_atualizam_preco_e_acertam_estoque(loja):
    linhas = importacao.ler_planilha(PLANILHA_ORLASOFT)
    plano = importacao.planejar(loja["casa"].id, linhas, atualizar_precos=True, ajustar_estoque=True)
    racao = plano[0]
    assert racao.acao == "atualizar"
    assert "preço 189,90 → 199,90" in racao.mudancas and "estoque 3 → 8" in racao.mudancas

    importacao.aplicar(loja["casa"], linhas, atualizar_precos=True, ajustar_estoque=True)
    racao = loja["racao"]
    assert racao.price == 199.9 and racao.variants[0].price == 199.9
    assert racao.variants[0].stock == 8
    ajuste = EstoqueMovimento.query.filter_by(product_id=racao.id).one()
    assert ajuste.tipo == "inventario" and ajuste.quantidade == Decimal("5")
    assert loja["racao"].ncm == "23091000", "dado fiscal que já existia não é trocado"


def test_telas_da_importacao(loja, client, monkeypatch):
    monkeypatch.setattr(login_utils, "_get_user", lambda: loja["owner"])
    casa_id = loja["casa"].id
    url = f"/casa-de-racao/{casa_id}/estoque/importar-produtos"
    assert "Importar planilha" in client.get(f"/casa-de-racao/{casa_id}/estoque").get_data(as_text=True)
    assert "Baixar a planilha modelo" in client.get(url).get_data(as_text=True)
    modelo = client.get(url + "/modelo.csv")
    assert modelo.status_code == 200 and modelo.data.decode("utf-8").startswith("﻿codigo_barras;codigo;nome")

    resposta = client.post(
        url,
        data={"arquivo": (io.BytesIO(PLANILHA_ORLASOFT), "orlasoft.csv"), "ajustar_estoque": "1"},
        content_type="multipart/form-data",
    )
    pagina = resposta.get_data(as_text=True)
    assert resposta.status_code == 200 and "Prévia: 6 linha(s)" in pagina and "Gravar 5 produto(s)" in pagina
    assert Product.query.filter_by(casa_de_racao_id=casa_id).count() == 2, "a prévia não grava nada"

    resposta = client.post(url, data={"acao": "confirmar", "previa": _previa(pagina), "ajustar_estoque": "1"})
    assert resposta.status_code == 302 and resposta.headers["Location"].endswith(f"/casa-de-racao/{casa_id}/estoque")
    assert Product.query.filter_by(casa_de_racao_id=casa_id).count() == 5
    assert loja["racao"].variants[0].stock == 8

    assert client.post(url, data={"acao": "confirmar", "previa": "não é a prévia"}).status_code == 302
    assert Product.query.filter_by(casa_de_racao_id=casa_id).count() == 5

    monkeypatch.setattr(login_utils, "_get_user", lambda: loja["outro"])
    assert client.get(url).status_code == 404
    assert client.get(url + "/modelo.csv").status_code == 404


def test_mesmo_nome_com_outro_codigo_entra_como_produto_novo(loja):
    """Coleira COL-G não é a Coleira COL-P da loja: não pode mexer nela."""
    coleira = loja["coleira"]
    coleira.name = "Coleira"
    coleira.variants[0].barcode = "7890000000011"
    db.session.commit()
    linhas = importacao.ler_planilha(_csv(
        "codigo_barras;codigo;nome;preco;estoque",
        "7890000000028;COL-G;Coleira;45,00;6",
        ";;Coleira;50,00;9",  # sem código: vale o nome
    ))
    plano = importacao.planejar(loja["casa"].id, linhas, atualizar_precos=True, ajustar_estoque=True)
    assert plano[0].acao == "criar" and any("outro código" in a for a in plano[0].avisos)
    assert plano[1].acao == "atualizar" and plano[1].product.id == coleira.id

    importacao.aplicar(loja["casa"], linhas[:1], atualizar_precos=True, ajustar_estoque=True)
    assert coleira.price == 30.0 and coleira.variants[0].stock == 1 and coleira.variants[0].sku == "COL-P"
    nova = ProductVariant.query.filter_by(barcode="7890000000028").one()
    assert nova.product_id != coleira.id and nova.sku == "COL-G" and nova.stock == 6


def test_catalogo_grande_chega_ao_fim(loja, client, monkeypatch):
    """3 mil produtos: a confirmação cabe no limite de formulário do Flask (500 mil bytes)."""
    monkeypatch.setattr(login_utils, "_get_user", lambda: loja["owner"])
    sorteio = random.Random(7)
    linhas = ["codigo_barras;codigo;nome;preco;custo;unidade;estoque;ncm;cfop;csosn;origem"]
    for i in range(3000):
        barras = "789" + "".join(sorteio.choice("0123456789") for _ in range(10))
        linhas.append(f"{barras};P{i:05d};Produto de teste número {i} sabor {sorteio.randint(1, 99)};"
                      f"{sorteio.randint(5, 300)},90;{sorteio.randint(2, 200)},10;UN;{sorteio.randint(0, 40)};"
                      "23091000;5102;102;0")
    planilha = _csv(*linhas)
    url = f"/casa-de-racao/{loja['casa'].id}/estoque/importar-produtos"
    pagina = client.post(url, data={"arquivo": (io.BytesIO(planilha), "grande.csv")},
                         content_type="multipart/form-data").get_data(as_text=True)
    assert "Prévia: 3000 linha(s)" in pagina
    previa = _previa(pagina)
    assert len(previa) < importacao.MAX_PREVIA
    resposta = client.post(url, data={"acao": "confirmar", "previa": previa})
    assert resposta.status_code == 302
    assert Product.query.filter_by(casa_de_racao_id=loja["casa"].id).count() == 3002


def test_previa_adulterada_ou_grande_demais_e_recusada():
    assert importacao.desempacotar(importacao.empacotar(b"nome;preco\nA;1\n")) == b"nome;preco\nA;1\n"
    assert importacao.desempacotar("") is None
    assert importacao.desempacotar("isto não é base64") is None
    bomba = importacao.base64.b64encode(gzip.compress(b"0" * (importacao.MAX_BYTES + 10))).decode()
    assert importacao.desempacotar(bomba) is None
