"""NFC-e em contingência off-line (tpEmis=9): emissão, envio quando a SEFAZ
volta e solução da nota normal que ficou sem resposta."""
from __future__ import annotations

import base64
from decimal import Decimal
from urllib.parse import unquote

import flask_login.utils as login_utils
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree

from extensions import db
from models import NfceDocumento, Product, ProductVariant, VendaBalcao
from providers.fiscal.xml_signature import load_pfx
from providers.nfce.xml_builder import PagamentoNfce
from providers.nfe.xml_builder import build_envi_nfe_xml
from services.loja_caixa import pdv
from services.loja_caixa.pdv import CaixaError
from services.loja_fiscal import nfce_service
from test_loja_nfce import NFE, XSD, _item, loja, sefaz  # noqa: F401 - fixtures

import pytest


def _emitir_sem_resposta(config, sefaz, cpf=None):
    sefaz.modo = "timeout"
    sefaz.consulta = "timeout"
    documento = nfce_service.emitir_nfce(
        config, itens=[_item()], pagamentos=[PagamentoNfce(t_pag="01", valor=Decimal("200"))], cpf=cpf
    )
    assert documento.status == "erro"
    return documento


def test_emissao_em_contingencia_monta_nota_offline_valida(loja, sefaz):
    config = loja["config"]
    original = _emitir_sem_resposta(config, sefaz, cpf="529.982.247-25")
    contingencia = nfce_service.contingencia_da_nota(original)

    assert contingencia.status == "contingencia" and contingencia.tp_emis == "9"
    assert contingencia.substitui_id == original.id
    assert contingencia.numero == original.numero + 1, "número novo; o sem resposta é resolvido depois"
    assert contingencia.chave[34] == "9"
    assert len(sefaz.lotes) == 1, "nada é transmitido na emissão em contingência"

    nfe = etree.fromstring(contingencia.xml_assinado.encode())
    ide = nfe.find(f".//{{{NFE}}}ide")
    assert ide.find(f"{{{NFE}}}tpEmis").text == "9"
    assert ide.find(f"{{{NFE}}}dhCont").text == ide.find(f"{{{NFE}}}dhEmi").text
    assert "contingencia" in ide.find(f"{{{NFE}}}xJust").text
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    lote = etree.fromstring(build_envi_nfe_xml(contingencia.xml_assinado, id_lote=1).encode())
    assert schema.validate(lote), schema.error_log

    # QR Code off-line: 7 parâmetros + assinatura RSA-SHA1 do certificado da loja.
    parametros = unquote(contingencia.qrcode.split("?p=", 1)[1]).split("|")
    assert parametros[:3] == [contingencia.chave, "3", "2"]
    assert parametros[4] == "189.90" and parametros[5:7] == ["2", "52998224725"]
    chave_privada, certificado = load_pfx(config.certificado_pfx(), config.certificado_senha())
    certificado.public_key().verify(
        base64.b64decode(parametros[7]), "|".join(parametros[:7]).encode(), padding.PKCS1v15(), hashes.SHA1()
    )


def test_envio_quando_a_sefaz_volta_e_inutiliza_a_nota_sem_resposta(loja, sefaz):
    config = loja["config"]
    original = _emitir_sem_resposta(config, sefaz)
    contingencia = nfce_service.contingencia_da_nota(original)

    # SEFAZ ainda fora: continua em contingência.
    contingencia = nfce_service.transmitir_contingencia(contingencia)
    assert contingencia.status == "contingencia"

    sefaz.modo = "autoriza"
    sefaz.consulta = "217"
    contingencia = nfce_service.transmitir_contingencia(contingencia)
    assert contingencia.status == "autorizada"
    assert db.session.get(NfceDocumento, original.id).status == "inutilizada"


def test_nota_sem_resposta_que_foi_autorizada_e_cancelada_por_substituicao(loja, sefaz):
    config = loja["config"]
    original = _emitir_sem_resposta(config, sefaz)
    contingencia = nfce_service.contingencia_da_nota(original)
    sefaz.modo = "autoriza"
    sefaz.consulta = "100"  # a nota normal tinha chegado na SEFAZ
    resumo = nfce_service.rotina_contingencia()
    assert resumo["autorizadas"] == 1 and resumo["erros"] == 0

    original = db.session.get(NfceDocumento, original.id)
    assert original.status == "cancelada"
    evento = etree.fromstring(sefaz.eventos[-1].encode())
    assert evento.find(f".//{{{NFE}}}tpEvento").text == "110112"
    assert evento.find(f".//{{{NFE}}}chNFeRef").text == db.session.get(NfceDocumento, contingencia.id).chave
    assert evento.find(f".//{{{NFE}}}infEvento").get("Id") == f"ID110112{original.chave}01"


def test_contingencia_rejeitada_e_reenviada_com_a_mesma_chave(loja, sefaz):
    """O cupom off-line já está com o cliente: corrigir e reenviar não pode trocar a chave."""
    config = loja["config"]
    original = _emitir_sem_resposta(config, sefaz)
    contingencia = nfce_service.contingencia_da_nota(original)
    chave, qrcode = contingencia.chave, contingencia.qrcode
    dh_cont = etree.fromstring(contingencia.xml_assinado.encode()).find(f".//{{{NFE}}}ide/{{{NFE}}}dhCont").text

    sefaz.modo = "rejeita"
    contingencia = nfce_service.transmitir_contingencia(contingencia)
    assert contingencia.status == "rejeitada" and contingencia.tp_emis == "9"

    # Reenvio sem resposta: volta para a contingência (o job tenta de novo), não para "erro".
    sefaz.modo = "timeout"
    contingencia = nfce_service.reenviar_nfce(contingencia)
    assert contingencia.status == "contingencia"

    sefaz.modo = "autoriza"
    sefaz.consulta = "217"
    documento = nfce_service.transmitir_contingencia(contingencia)
    assert documento.status == "autorizada"
    assert documento.chave == chave and documento.qrcode == qrcode
    ide = etree.fromstring(sefaz.lotes[-1].encode()).find(f".//{{{NFE}}}ide")
    assert ide.find(f"{{{NFE}}}tpEmis").text == "9" and ide.find(f"{{{NFE}}}dhCont").text == dh_cont
    assert db.session.get(NfceDocumento, original.id).status == "inutilizada"


def test_job_nao_trava_nas_substituicoes_ja_resolvidas(loja, sefaz):
    config = loja["config"]
    primeira = _emitir_sem_resposta(config, sefaz)
    substituta_1 = nfce_service.contingencia_da_nota(primeira)
    segunda = _emitir_sem_resposta(config, sefaz)
    substituta_2 = nfce_service.contingencia_da_nota(segunda)

    sefaz.modo = "autoriza"
    sefaz.consulta = "217"
    nfce_service.transmitir_contingencia(substituta_1)
    assert db.session.get(NfceDocumento, primeira.id).status == "inutilizada"
    sefaz.consulta = "timeout"  # a segunda fica sem solução nesta passada
    nfce_service.transmitir_contingencia(substituta_2)
    assert db.session.get(NfceDocumento, substituta_2.id).status == "autorizada"
    assert db.session.get(NfceDocumento, segunda.id).status == "erro"

    sefaz.consulta = "217"
    resumo = nfce_service.rotina_contingencia(limite=1)
    assert resumo["resolvidas"] == 1
    assert db.session.get(NfceDocumento, segunda.id).status == "inutilizada"


def test_caixa_entra_em_contingencia_sozinho_quando_ligado(loja, sefaz, client, monkeypatch):
    casa, config = loja["casa"], loja["config"]
    config.ativo = True
    config.contingencia_automatica = True
    produto = Product(name="Ração", price=150.0, stock=5, casa_de_racao_id=casa.id, ncm="23091000")
    produto.variants.append(ProductVariant(name="15 kg", price=150.0, stock=5, status="active"))
    db.session.add(produto)
    db.session.commit()
    pdv.abrir_caixa(casa.id, valor_abertura="0", usuario_id=loja["owner"].id)
    sefaz.modo = "timeout"
    sefaz.consulta = "timeout"

    monkeypatch.setattr(login_utils, "_get_user", lambda: loja["owner"])
    resposta = client.post(
        f"/casa-de-racao/{casa.id}/caixa/venda",
        json={
            "chave": "venda-contingencia-1",
            "itens": [{"product_id": produto.id, "variant_id": produto.variants[0].id, "quantidade": "1"}],
            "pagamentos": [{"t_pag": "01", "valor": "150"}],
            "emitir_nfce": True,
        },
    ).get_json()
    assert resposta["ok"] and resposta["nfce"]["contingencia"] is True
    venda = db.session.get(VendaBalcao, resposta["venda_id"])
    assert venda.nfce.status == "contingencia" and venda.nfce.tp_emis == "9"
    assert "EMITIDA EM CONTINGÊNCIA" in client.get(resposta["nfce"]["cupom_url"]).get_data(as_text=True)

    with pytest.raises(CaixaError, match="contingência"):
        pdv.cancelar_venda(venda, motivo="Cliente desistiu da compra no balcão", usuario_id=None)
    with pytest.raises(CaixaError, match="contingência"):
        pdv.emitir_nfce_venda(venda)

    sefaz.modo = "autoriza"
    sefaz.consulta = "217"
    assert client.post(f"/casa-de-racao/{casa.id}/nfce/{venda.nfce_documento_id}/transmitir").status_code == 302
    venda = db.session.get(VendaBalcao, venda.id)
    assert venda.nfce.status == "autorizada"


def test_botao_de_contingencia_na_venda(loja, sefaz, client, monkeypatch):
    casa, config = loja["casa"], loja["config"]
    config.ativo = True
    produto = Product(name="Coleira", price=30.0, stock=5, casa_de_racao_id=casa.id, ncm="42010090")
    produto.variants.append(ProductVariant(name="P", price=30.0, stock=5, status="active"))
    db.session.add(produto)
    db.session.commit()
    caixa = pdv.abrir_caixa(casa.id, valor_abertura="0", usuario_id=loja["owner"].id)
    venda = pdv.registrar_venda(
        casa.id, caixa,
        itens=[{"product_id": produto.id, "variant_id": produto.variants[0].id, "quantidade": "1"}],
        pagamentos=[{"t_pag": "01", "valor": "30"}],
        emitir_nfce=True,
    )
    sefaz.modo = "timeout"
    sefaz.consulta = "timeout"
    pdv.emitir_nfce_venda(venda)
    venda = db.session.get(VendaBalcao, venda.id)
    assert venda.nfce.status == "erro"

    monkeypatch.setattr(login_utils, "_get_user", lambda: loja["owner"])
    pagina = client.get(f"/casa-de-racao/{casa.id}/caixa/venda/{venda.id}").get_data(as_text=True)
    assert "Emitir em contingência" in pagina
    assert client.post(f"/casa-de-racao/{casa.id}/caixa/venda/{venda.id}/contingencia").status_code == 302
    venda = db.session.get(VendaBalcao, venda.id)
    assert venda.nfce.status == "contingencia" and venda.nfce.substitui_id
