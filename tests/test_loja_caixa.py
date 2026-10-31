"""Caixa (PDV) e estoque da loja: sessão, vendas, NFC-e, cancelamento e telas.

A SEFAZ é o mesmo dublê dos testes da NFC-e, que valida cada lote contra o
esquema oficial.
"""
from __future__ import annotations

from decimal import Decimal

import flask_login.utils as login_utils
import pytest
from lxml import etree

from extensions import db
from models import (
    CaixaSessao,
    CasaDeRacao,
    EstoqueMovimento,
    LojaFiscalConfig,
    NfceDocumento,
    Product,
    ProductVariant,
    User,
    VendaBalcao,
)
from security.crypto import clear_crypto_cache
from services.loja_caixa import estoque, pdv
from services.loja_caixa.pdv import CaixaError, VendaRepetida
from services.loja_fiscal import nfce_service
from test_loja_nfce import NFE, XSD, FakeSefaz, _pfx

CNPJ = "12.345.678/0001-95"
GTIN = "7891000315507"


@pytest.fixture()
def loja(app, monkeypatch):
    monkeypatch.setenv("FISCAL_MASTER_KEY", "chave-mestra-teste-caixa-loja")
    clear_crypto_cache()
    owner = User(name="Renato", email="renato-caixa@example.com")
    owner.set_password("x")
    outro = User(name="Outro", email="outro-caixa@example.com")
    outro.set_password("x")
    db.session.add_all([owner, outro])
    db.session.flush()
    casa = CasaDeRacao(nome="Cat Dog", tipo="petshop", owner_id=owner.id, status="ativa", cnpj=CNPJ)
    outra_casa = CasaDeRacao(nome="Outra", owner_id=outro.id, status="ativa")
    db.session.add_all([casa, outra_casa])
    db.session.flush()

    racao = Product(name="Ração Premium", price=150.0, stock=10, casa_de_racao_id=casa.id, ncm="23091000")
    racao.variants.append(ProductVariant(name="15 kg", price=150.0, stock=10, barcode=GTIN, status="active"))
    granel = Product(name="Ração a granel", price=12.0, stock=20, casa_de_racao_id=casa.id, ncm="23091000", unidade="KG")
    granel.variants.append(ProductVariant(name="Granel", price=12.0, stock=20, status="active"))
    coleira = Product(name="Coleira", price=30.0, stock=3, casa_de_racao_id=casa.id, status="inactive")
    coleira.variants.append(ProductVariant(name="P", price=30.0, stock=3, status="active", sku="COL-P"))
    alheio = Product(name="Produto alheio", price=10.0, stock=5, casa_de_racao_id=outra_casa.id, ncm="23091000")
    alheio.variants.append(ProductVariant(name="Único", price=10.0, stock=5, status="active"))
    db.session.add_all([racao, granel, coleira, alheio])
    db.session.commit()
    return {
        "casa": casa,
        "owner": owner,
        "outro": outro,
        "racao": racao,
        "granel": granel,
        "coleira": coleira,
        "alheio": alheio,
    }


@pytest.fixture()
def fiscal(loja):
    config = LojaFiscalConfig(
        casa_de_racao_id=loja["casa"].id,
        cnpj=CNPJ,
        razao_social="Cat Dog Pet Shop Ltda",
        nome_fantasia="Cat Dog",
        inscricao_estadual="481234567110",
        logradouro="Rua Oito",
        numero="2054A",
        bairro="Jardim Santa Rita",
        cep="14620000",
    )
    db.session.add(config)
    db.session.flush()
    nfce_service.salvar_certificado(config, _pfx(), "senha")
    config.ativo = True
    db.session.commit()
    return config


@pytest.fixture()
def sefaz(monkeypatch):
    fake = FakeSefaz(schema=etree.XMLSchema(etree.parse(str(XSD))))
    monkeypatch.setattr(nfce_service, "_cliente", lambda config, ambiente=None: fake)
    return fake


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def _variante(produto) -> ProductVariant:
    return produto.variants[0]


def _abrir(loja, valor="100") -> CaixaSessao:
    return pdv.abrir_caixa(loja["casa"].id, valor_abertura=valor, usuario_id=loja["owner"].id)


def _item(produto, quantidade="1", **extra):
    dados = {"product_id": produto.id, "variant_id": _variante(produto).id, "quantidade": quantidade}
    dados.update(extra)
    return dados


# ------------------------------------------------------------------ sessão

def test_um_caixa_aberto_por_loja(loja):
    sessao = _abrir(loja)
    assert sessao.status == "aberto"
    assert sessao.valor_abertura == Decimal("100.00")
    with pytest.raises(CaixaError, match="Já existe"):
        _abrir(loja)


def test_venda_exige_caixa_aberto(loja):
    with pytest.raises(CaixaError, match="Abra o caixa"):
        pdv.registrar_venda(
            loja["casa"].id, None,
            itens=[_item(loja["racao"])],
            pagamentos=[{"t_pag": "01", "valor": "150"}],
        )


# --------------------------------------------------------------- catálogo

def test_busca_por_codigo_sku_e_nome(loja):
    casa_id = loja["casa"].id
    por_codigo = pdv.buscar_itens(casa_id, GTIN)
    assert [i["descricao"] for i in por_codigo] == ["Ração Premium"]
    assert por_codigo[0]["preco"] == "150.00"
    assert por_codigo[0]["estoque"] == "10"

    # SKU exato e produto fora da loja online também vendem no balcão.
    por_sku = pdv.buscar_itens(casa_id, "col-p")
    assert por_sku[0]["descricao"] == "Coleira" and por_sku[0]["online"] is False

    # Sem acento, com acento ou em maiúsculas: acha do mesmo jeito.
    for termo in ("racao granel", "RAÇÃO gra", "granel"):
        por_nome = pdv.buscar_itens(casa_id, termo)
        assert [i["descricao"] for i in por_nome] == ["Ração a granel"], termo
    assert por_nome[0]["fracionado"] is True
    assert {i["descricao"] for i in pdv.buscar_itens(casa_id, "racao")} == {"Ração Premium", "Ração a granel"}

    # Nunca devolve produto de outra loja.
    assert pdv.buscar_itens(casa_id, "alheio") == []


def test_vincular_codigo_de_barras(loja):
    casa_id = loja["casa"].id
    coleira = loja["coleira"]
    variante = pdv.vincular_codigo_barras(casa_id, product_id=coleira.id, variant_id=None, codigo=" 7890000000017 ")
    assert variante.barcode == "7890000000017"
    assert pdv.buscar_itens(casa_id, "7890000000017")[0]["product_id"] == coleira.id
    with pytest.raises(CaixaError, match="já está em"):
        pdv.vincular_codigo_barras(casa_id, product_id=coleira.id, variant_id=None, codigo=GTIN)
    with pytest.raises(CaixaError, match="não encontrado"):
        pdv.vincular_codigo_barras(casa_id, product_id=loja["alheio"].id, variant_id=None, codigo="123")


# ------------------------------------------------------------------- venda

def test_venda_em_dinheiro_baixa_estoque_e_registra_movimento(loja):
    sessao = _abrir(loja)
    racao = loja["racao"]
    venda = pdv.registrar_venda(
        loja["casa"].id, sessao,
        itens=[_item(racao, "2")],
        pagamentos=[{"t_pag": "01", "valor": "350,00"}],
        usuario_id=loja["owner"].id,
    )
    assert venda.status == "concluida"
    assert venda.total == Decimal("300.00")
    assert venda.troco == Decimal("50.00")
    item = venda.itens[0]
    assert item.gtin == GTIN and item.ncm == "23091000" and item.unidade == "UN"

    db.session.refresh(racao)
    assert _variante(racao).stock == 8
    assert racao.stock == 8
    movimento = EstoqueMovimento.query.filter_by(referencia_id=venda.id, tipo="venda_balcao").one()
    assert movimento.quantidade == Decimal("-2") and movimento.saldo_apos == Decimal("8")

    resumo = pdv.resumo_caixa(sessao)
    assert resumo["quantidade_vendas"] == 1
    assert resumo["dinheiro_vendas"] == Decimal("300.00")
    assert resumo["dinheiro_esperado"] == Decimal("400.00")


def test_desconto_da_venda_e_rateado_entre_os_itens(loja):
    sessao = _abrir(loja)
    venda = pdv.registrar_venda(
        loja["casa"].id, sessao,
        itens=[_item(loja["racao"]), _item(loja["coleira"])],
        pagamentos=[{"t_pag": "20", "valor": "170"}],
        desconto_venda="10",
    )
    assert venda.subtotal == Decimal("180.00")
    assert venda.desconto == Decimal("10.00")
    assert venda.total == Decimal("170.00")
    assert sum(i.desconto for i in venda.itens) == Decimal("10.00")
    assert sum(i.total for i in venda.itens) == venda.total


@pytest.mark.parametrize(
    "itens_fn, pagamentos, mensagem",
    [
        (lambda l: [_item(l["racao"])], [{"t_pag": "01", "valor": "100"}], "Faltam R\\$ 50,00"),
        (lambda l: [_item(l["racao"])], [{"t_pag": "03", "valor": "200"}], "Só pagamento em dinheiro"),
        (lambda l: [_item(l["racao"], "1,5")], [{"t_pag": "01", "valor": "300"}], "unidade inteira"),
        (lambda l: [_item(l["alheio"])], [{"t_pag": "01", "valor": "10"}], "não pertence"),
        (lambda l: [_item(l["racao"], desconto="150")], [{"t_pag": "01", "valor": "150"}], "Desconto inválido"),
        (lambda l: [_item(l["racao"])], [{"t_pag": "77", "valor": "150"}], "Forma de pagamento"),
        (lambda l: [], [{"t_pag": "01", "valor": "1"}], "Adicione"),
    ],
)
def test_venda_invalida_nao_grava_nada(loja, itens_fn, pagamentos, mensagem):
    sessao = _abrir(loja)
    with pytest.raises(CaixaError, match=mensagem):
        pdv.registrar_venda(loja["casa"].id, sessao, itens=itens_fn(loja), pagamentos=pagamentos)
    db.session.rollback()
    assert VendaBalcao.query.count() == 0
    assert EstoqueMovimento.query.count() == 0
    assert _variante(loja["racao"]).stock == 10


def test_granel_guarda_fracao_sem_mudar_a_coluna_inteira(loja):
    sessao = _abrir(loja)
    granel = loja["granel"]
    pdv.registrar_venda(
        loja["casa"].id, sessao,
        itens=[_item(granel, "2,5")],
        pagamentos=[{"t_pag": "01", "valor": "30"}],
    )
    variante = _variante(granel)
    assert variante.stock == 17  # 20 - 2,5 = 17,5 → coluna inteira 17
    assert estoque.saldo(granel, variante) == Decimal("17.5")
    pdv.registrar_venda(
        loja["casa"].id, sessao,
        itens=[_item(granel, "0.5")],
        pagamentos=[{"t_pag": "01", "valor": "6"}],
    )
    assert variante.stock == 17
    assert estoque.saldo(granel, variante) == Decimal("17")
    # Venda além do saldo não deixa a coluna negativa (como na loja online).
    pdv.registrar_venda(
        loja["casa"].id, sessao,
        itens=[_item(granel, "18")],
        pagamentos=[{"t_pag": "01", "valor": "216"}],
    )
    assert variante.stock == 0 and estoque.saldo(granel, variante) == Decimal("0")


def test_chave_repetida_nao_cobra_duas_vezes(loja):
    sessao = _abrir(loja)
    argumentos = dict(
        itens=[_item(loja["racao"])],
        pagamentos=[{"t_pag": "01", "valor": "150"}],
        chave_cliente="caixa-1-venda-abc",
    )
    venda = pdv.registrar_venda(loja["casa"].id, sessao, **argumentos)
    with pytest.raises(VendaRepetida) as erro:
        pdv.registrar_venda(loja["casa"].id, sessao, **argumentos)
    assert erro.value.venda.id == venda.id
    assert VendaBalcao.query.count() == 1
    assert _variante(loja["racao"]).stock == 9


# ------------------------------------------------------------------- NFC-e

def test_venda_com_nfce_autorizada(loja, fiscal, sefaz):
    sessao = _abrir(loja)
    venda = pdv.registrar_venda(
        loja["casa"].id, sessao,
        itens=[_item(loja["racao"]), _item(loja["granel"], "1,25")],
        pagamentos=[{"t_pag": "04", "valor": "165"}],
        emitir_nfce=True,
    )
    documento = pdv.emitir_nfce_venda(venda, cpf="529.982.247-25", usuario_id=loja["owner"].id)
    assert documento.status == "autorizada"
    assert documento.origem == "venda_balcao" and documento.origem_id == venda.id
    venda = db.session.get(VendaBalcao, venda.id)
    assert venda.nfce_documento_id == documento.id and venda.nfce_erro is None

    nfe = etree.fromstring(sefaz.lotes[-1].encode()).find(f".//{{{NFE}}}NFe")
    dets = nfe.findall(f".//{{{NFE}}}det")
    assert dets[0].find(f"{{{NFE}}}prod/{{{NFE}}}cEAN").text == GTIN
    assert dets[1].find(f"{{{NFE}}}prod/{{{NFE}}}uCom").text == "KG"
    assert dets[1].find(f"{{{NFE}}}prod/{{{NFE}}}qCom").text == "1.2500"
    assert nfe.find(f".//{{{NFE}}}dest/{{{NFE}}}CPF").text == "52998224725"
    assert nfe.find(f".//{{{NFE}}}detPag/{{{NFE}}}tPag").text == "04"
    assert nfe.find(f".//{{{NFE}}}total/{{{NFE}}}ICMSTot/{{{NFE}}}vNF").text == "165.00"

    with pytest.raises(CaixaError, match="já tem NFC-e"):
        pdv.emitir_nfce_venda(venda)


def test_nfce_rejeitada_mantem_venda_e_reenvio_usa_cadastro_corrigido(loja, fiscal, sefaz):
    sessao = _abrir(loja)
    coleira = loja["coleira"]  # sem NCM
    venda = pdv.registrar_venda(
        loja["casa"].id, sessao,
        itens=[_item(coleira)],
        pagamentos=[{"t_pag": "01", "valor": "30"}],
        emitir_nfce=True,
    )
    with pytest.raises(CaixaError, match="NCM"):
        pdv.emitir_nfce_venda(venda)
    venda = db.session.get(VendaBalcao, venda.id)
    assert venda.status == "concluida" and "NCM" in venda.nfce_erro
    assert NfceDocumento.query.count() == 0
    assert _variante(coleira).stock == 2  # a venda continua valendo

    coleira.ncm = "42010090"
    db.session.commit()
    sefaz.modo = "rejeita"
    documento = pdv.emitir_nfce_venda(venda)
    assert documento.status == "rejeitada"
    venda = db.session.get(VendaBalcao, venda.id)
    assert venda.nfce_erro.startswith("NFC-e rejeitada")

    sefaz.modo = "autoriza"
    documento = pdv.emitir_nfce_venda(venda)
    assert documento.status == "autorizada"
    assert NfceDocumento.query.count() == 1  # mesmo número, nota remontada
    assert db.session.get(VendaBalcao, venda.id).nfce_erro is None


def test_cancelar_venda_cancela_nfce_e_devolve_estoque(loja, fiscal, sefaz):
    sessao = _abrir(loja)
    racao = loja["racao"]
    venda = pdv.registrar_venda(
        loja["casa"].id, sessao,
        itens=[_item(racao, "3")],
        pagamentos=[{"t_pag": "01", "valor": "450"}],
        emitir_nfce=True,
    )
    pdv.emitir_nfce_venda(venda)
    assert _variante(racao).stock == 7

    with pytest.raises(CaixaError, match="15 caracteres"):
        pdv.cancelar_venda(venda, motivo="curto", usuario_id=None)

    sefaz.evento_cstat = "501"
    with pytest.raises(CaixaError, match="não aceitou"):
        pdv.cancelar_venda(venda, motivo="Cliente desistiu da compra no balcão", usuario_id=None)
    assert db.session.get(VendaBalcao, venda.id).status == "concluida"
    assert _variante(racao).stock == 7

    sefaz.evento_cstat = "135"
    venda = pdv.cancelar_venda(db.session.get(VendaBalcao, venda.id), motivo="Cliente desistiu da compra no balcão", usuario_id=None)
    assert venda.status == "cancelada"
    assert venda.nfce.status == "cancelada"
    assert _variante(racao).stock == 10
    assert EstoqueMovimento.query.filter_by(tipo="cancelamento_venda").count() == 1
    assert pdv.resumo_caixa(sessao)["dinheiro_esperado"] == Decimal("100.00")
    with pytest.raises(CaixaError, match="já foi cancelada"):
        pdv.cancelar_venda(venda, motivo="Cliente desistiu da compra no balcão", usuario_id=None)


def test_nao_cancela_venda_com_nfce_sem_resposta(loja, fiscal, sefaz):
    sessao = _abrir(loja)
    venda = pdv.registrar_venda(
        loja["casa"].id, sessao,
        itens=[_item(loja["racao"])],
        pagamentos=[{"t_pag": "01", "valor": "150"}],
        emitir_nfce=True,
    )
    sefaz.modo = "timeout"
    documento = pdv.emitir_nfce_venda(venda)
    assert documento.status == "erro"
    with pytest.raises(CaixaError, match="ainda não tem resposta"):
        pdv.cancelar_venda(db.session.get(VendaBalcao, venda.id), motivo="Cliente desistiu da compra no balcão", usuario_id=None)


# ------------------------------------------------------------ fechamento

def test_sangria_suprimento_e_fechamento(loja):
    sessao = _abrir(loja, "50")
    pdv.registrar_venda(
        loja["casa"].id, sessao,
        itens=[_item(loja["coleira"])],
        pagamentos=[{"t_pag": "01", "valor": "50"}, {"t_pag": "20", "valor": "0"}],
    )
    pdv.movimentar_caixa(sessao, tipo="suprimento", valor="20", motivo="moedas", usuario_id=None)
    with pytest.raises(CaixaError, match="maior que o dinheiro"):
        pdv.movimentar_caixa(sessao, tipo="sangria", valor="500", motivo=None, usuario_id=None)
    pdv.movimentar_caixa(sessao, tipo="sangria", valor="40", motivo="depósito", usuario_id=None)
    resumo = pdv.resumo_caixa(sessao)
    # 50 abertura + 30 (50 pagos - 20 troco) + 20 reforço - 40 retirada
    assert resumo["dinheiro_esperado"] == Decimal("60.00")

    pdv.fechar_caixa(sessao, valor_contado="58,00", usuario_id=None, observacao="faltou moeda")
    assert sessao.status == "fechado"
    assert sessao.valor_esperado == Decimal("60.00")
    assert sessao.diferenca == Decimal("-2.00")
    assert pdv.caixa_aberto(loja["casa"].id) is None
    _abrir(loja)  # pode abrir de novo depois de fechar


# ------------------------------------------------------------------- telas

def test_telas_do_caixa_e_venda_por_json(loja, fiscal, sefaz, client, monkeypatch):
    _login(monkeypatch, loja["owner"])
    casa_id = loja["casa"].id
    assert "Abrir o caixa" in client.get(f"/casa-de-racao/{casa_id}/caixa").get_data(as_text=True)
    assert client.post(f"/casa-de-racao/{casa_id}/caixa/abrir", data={"valor_abertura": "80"}).status_code == 302

    pagina = client.get(f"/casa-de-racao/{casa_id}/caixa").get_data(as_text=True)
    assert 'id="pdv-busca"' in pagina and "Emitir NFC-e" in pagina

    busca = client.get(f"/casa-de-racao/{casa_id}/caixa/produtos?q={GTIN}").get_json()
    assert busca["itens"][0]["descricao"] == "Ração Premium"

    corpo = {
        "chave": "venda-tela-1",
        "itens": [{"product_id": loja["racao"].id, "variant_id": _variante(loja["racao"]).id, "quantidade": "1", "preco_unitario": "150,00"}],
        "pagamentos": [{"t_pag": "01", "valor": "200"}],
        "emitir_nfce": True,
        "cpf": "",
    }
    resposta = client.post(f"/casa-de-racao/{casa_id}/caixa/venda", json=corpo).get_json()
    assert resposta["ok"] and resposta["troco"] == "50.00"
    assert resposta["nfce"]["autorizada"] is True
    assert resposta["nfce"]["cupom_url"].endswith("/cupom")

    repetida = client.post(f"/casa-de-racao/{casa_id}/caixa/venda", json=corpo).get_json()
    assert repetida["venda_id"] == resposta["venda_id"]
    assert len(sefaz.lotes) == 1 and VendaBalcao.query.count() == 1

    invalida = client.post(f"/casa-de-racao/{casa_id}/caixa/venda", json={**corpo, "chave": "x2", "pagamentos": []})
    assert invalida.status_code == 400 and "pagou" in invalida.get_json()["erro"]

    venda_id = resposta["venda_id"]
    for caminho in (
        f"/casa-de-racao/{casa_id}/caixa/venda/{venda_id}",
        f"/casa-de-racao/{casa_id}/caixa/venda/{venda_id}/comprovante",
        f"/casa-de-racao/{casa_id}/caixa/venda/{venda_id}/comprovante?largura=58",
        f"/casa-de-racao/{casa_id}/caixa/vendas",
        f"/casa-de-racao/{casa_id}/caixa/fechar",
        f"/casa-de-racao/{casa_id}/estoque",
        f"/casa-de-racao/{casa_id}/estoque?filtro=sem_ncm",
        f"/casa-de-racao/{casa_id}/estoque/produto/{loja['racao'].id}",
        f"/casa-de-racao/{casa_id}/nfce/{resposta['nfce']['cupom_url'].split('/')[-2]}",
    ):
        assert client.get(caminho).status_code == 200, caminho

    assert client.post(f"/casa-de-racao/{casa_id}/caixa/fechar", data={"valor_contado": "230"}).status_code == 302
    sessao = CaixaSessao.query.one()
    assert sessao.status == "fechado" and sessao.diferenca == Decimal("0.00")
    assert client.get(f"/casa-de-racao/{casa_id}/caixa/sessao/{sessao.id}").status_code == 200


def test_outra_loja_nao_acessa_o_caixa(loja, client, monkeypatch):
    _login(monkeypatch, loja["outro"])
    casa_id = loja["casa"].id
    assert client.get(f"/casa-de-racao/{casa_id}/caixa").status_code == 404
    assert client.get(f"/casa-de-racao/{casa_id}/caixa/produtos?q=racao").status_code == 404
    assert client.post(f"/casa-de-racao/{casa_id}/caixa/venda", json={}).status_code == 404
    assert client.get(f"/casa-de-racao/{casa_id}/estoque").status_code == 404


def test_estoque_produto_salva_dados_fiscais_codigo_e_ajuste(loja, client, monkeypatch):
    _login(monkeypatch, loja["owner"])
    casa_id = loja["casa"].id
    coleira = loja["coleira"]
    variante = _variante(coleira)
    resposta = client.post(
        f"/casa-de-racao/{casa_id}/estoque/produto/{coleira.id}",
        data={
            "ncm": "4201.00.90",
            "cest": "",
            "csosn": "102",
            "cfop": "",
            "origem": "0",
            "unidade": "UN",
            f"codigo_barras_{variante.id}": "7890000000017",
            f"sku_{variante.id}": "COL-P",
            f"saldo_{variante.id}": "12",
            "motivo": "contagem do mês",
            "inventario": "1",
        },
    )
    assert resposta.status_code == 302
    db.session.refresh(coleira)
    assert coleira.ncm == "42010090" and coleira.csosn == "102"
    assert variante.barcode == "7890000000017" and variante.stock == 12
    assert coleira.stock == 12
    movimento = EstoqueMovimento.query.filter_by(product_id=coleira.id).one()
    assert movimento.tipo == "inventario" and movimento.quantidade == Decimal("9")

    # Código já usado em outro produto da loja é recusado sem gravar nada.
    client.post(
        f"/casa-de-racao/{casa_id}/estoque/produto/{coleira.id}",
        data={"ncm": "42010090", "csosn": "", "origem": "0", "unidade": "UN", f"codigo_barras_{variante.id}": GTIN, f"saldo_{variante.id}": "1"},
    )
    db.session.refresh(variante)
    assert variante.barcode == "7890000000017" and variante.stock == 12


def test_venda_online_baixa_tambem_a_apresentacao(loja):
    from blueprints.loja import _baixar_apresentacao_venda_online

    racao = loja["racao"]
    variante = _variante(racao)

    class Pedido:
        id = 77
        public_reference = "PO-77"

    class ItemPedido:
        quantity = 2
        variant = variante

    racao.stock = racao.stock - 2  # o webhook já baixa product.stock antes
    _baixar_apresentacao_venda_online(racao, ItemPedido(), Pedido())
    db.session.commit()
    assert variante.stock == 8 and racao.stock == 8
    movimento = EstoqueMovimento.query.filter_by(tipo="venda_online").one()
    assert movimento.referencia_id == 77 and movimento.saldo_apos == Decimal("8")
