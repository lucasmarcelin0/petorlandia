"""Banho e tosa da loja: tabela por porte, pacote mensal, agenda e cobrança."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import flask_login.utils as login_utils
import pytest

from extensions import db
from models import (
    Animal,
    CasaDeRacao,
    GroomingPlan,
    GroomingSessao,
    GroomingSubscription,
    User,
    VendaBalcao,
)
from services import loja_banho_tosa as banho_tosa
from services.loja_banho_tosa import BanhoTosaError
from services.loja_caixa import pdv
from services.loja_caixa.pdv import CaixaError
from time_utils import BR_TZ


@pytest.fixture()
def loja(app):
    owner = User(name="Renato", email="renato-bt@example.com")
    owner.set_password("x")
    tutor = User(name="Ana", email="ana-bt@example.com")
    tutor.set_password("x")
    outro = User(name="Outro", email="outro-bt@example.com")
    outro.set_password("x")
    db.session.add_all([owner, tutor, outro])
    db.session.flush()
    casa = CasaDeRacao(nome="Cat Dog", tipo="petshop", owner_id=owner.id, status="ativa", telefone="(16) 99858-0506")
    db.session.add(casa)
    db.session.flush()
    tutor.casa_de_racao_id = casa.id
    pequeno = Animal(name="Mel", user_id=tutor.id, casa_de_racao_id=casa.id, peso=8.0)
    grande = Animal(name="Thor", user_id=tutor.id, casa_de_racao_id=casa.id, peso=42.0)
    db.session.add_all([pequeno, grande])
    planos = {
        "pequeno": GroomingPlan(casa_de_racao_id=casa.id, name="Banho porte pequeno", service_type="banho",
                                price=Decimal("40"), cobranca="avulso", peso_max_kg=Decimal("10")),
        "grande": GroomingPlan(casa_de_racao_id=casa.id, name="Banho porte grande", service_type="banho",
                               price=Decimal("120"), cobranca="avulso", peso_min_kg=Decimal("40")),
        "pacote": GroomingPlan(casa_de_racao_id=casa.id, name="4 banhos no mês", service_type="banho",
                               price=Decimal("160"), cobranca="mensal", sessions_per_month=4, peso_max_kg=Decimal("10")),
    }
    db.session.add_all(planos.values())
    db.session.commit()
    return {"casa": casa, "owner": owner, "tutor": tutor, "outro": outro, "mel": pequeno, "thor": grande, **planos}


def _quando(dia=5, hora=10):
    return datetime(2026, 11, dia, hora, 0, tzinfo=BR_TZ)


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def test_porte_por_faixa_de_peso(loja):
    assert loja["pequeno"].porte_label == "Até 10 kg"
    assert loja["grande"].porte_label == "Acima de 40 kg"
    meio = GroomingPlan(name="x", price=1, peso_min_kg=Decimal("20"), peso_max_kg=Decimal("30.5"))
    assert meio.porte_label == "De 20 a 30,5 kg"
    assert GroomingPlan(name="y", price=1).porte_label == "Qualquer porte"
    assert loja["pequeno"].atende_peso(8) and not loja["pequeno"].atende_peso(12)
    assert loja["grande"].atende_peso(None), "animal sem peso cadastrado pode agendar"
    sugeridos = banho_tosa.planos_para_peso(banho_tosa.planos_da_loja(loja["casa"].id), 42)
    assert [p.name for p in sugeridos] == ["Banho porte grande"]


def test_agendar_avulso_confere_o_porte(loja):
    casa = loja["casa"]
    sessao = banho_tosa.agendar(casa, animal_id=loja["mel"].id, plan_id=loja["pequeno"].id, quando=_quando())
    assert sessao.valor == Decimal("40") and sessao.subscription_id is None
    with pytest.raises(BanhoTosaError, match="pesa 42"):
        banho_tosa.agendar(casa, animal_id=loja["thor"].id, plan_id=loja["pequeno"].id, quando=_quando())


def test_pacote_mensal_desconta_e_limita(loja):
    casa = loja["casa"]
    with pytest.raises(BanhoTosaError, match="não tem o plano mensal"):
        banho_tosa.agendar(casa, animal_id=loja["mel"].id, plan_id=loja["pacote"].id, quando=_quando())
    assinatura = GroomingSubscription(plan_id=loja["pacote"].id, animal_id=loja["mel"].id, user_id=loja["tutor"].id, active=True)
    db.session.add(assinatura)
    db.session.commit()
    sessoes = [
        banho_tosa.agendar(casa, animal_id=loja["mel"].id, plan_id=loja["pacote"].id, quando=_quando(dia))
        for dia in (3, 10, 17, 24)
    ]
    with pytest.raises(BanhoTosaError, match="já foi usado"):
        banho_tosa.agendar(casa, animal_id=loja["mel"].id, plan_id=loja["pacote"].id, quando=_quando(28))
    # Cancelar devolve a sessão ao pacote; o mês seguinte começa zerado.
    banho_tosa.mudar_status(sessoes[3], "cancelado")
    banho_tosa.agendar(casa, animal_id=loja["mel"].id, plan_id=loja["pacote"].id, quando=_quando(28))
    banho_tosa.agendar(
        casa, animal_id=loja["mel"].id, plan_id=loja["pacote"].id, quando=datetime(2026, 12, 1, 9, tzinfo=BR_TZ)
    )
    assert banho_tosa.sessoes_no_mes(assinatura, _quando()) == 4


def test_cobrar_avulso_no_caixa(loja):
    casa = loja["casa"]
    sessao = banho_tosa.agendar(casa, animal_id=loja["mel"].id, plan_id=loja["pequeno"].id, quando=_quando())
    with pytest.raises(BanhoTosaError, match="Abra o caixa"):
        banho_tosa.cobrar_no_caixa(casa, sessao, caixa=None, pagamentos=[{"t_pag": "01", "valor": "50"}])
    caixa = pdv.abrir_caixa(casa.id, valor_abertura="20", usuario_id=loja["owner"].id)
    venda = banho_tosa.cobrar_no_caixa(casa, sessao, caixa=caixa, pagamentos=[{"t_pag": "01", "valor": "50"}])
    assert venda.total == Decimal("40.00") and venda.troco == Decimal("10.00")
    assert venda.emitir_nfce is False and venda.itens[0].product_id is None
    assert "Mel" in venda.itens[0].descricao
    assert sessao.status == "realizado" and sessao.venda_id == venda.id
    assert pdv.resumo_caixa(caixa)["dinheiro_esperado"] == Decimal("60.00")
    with pytest.raises(BanhoTosaError, match="já foi paga"):
        banho_tosa.cobrar_no_caixa(casa, sessao, caixa=caixa, pagamentos=[{"t_pag": "01", "valor": "40"}])
    with pytest.raises(CaixaError, match="NFS-e"):
        pdv.emitir_nfce_venda(venda)
    # Venda de serviço cancelada: não mexe em estoque e libera a sessão.
    pdv.cancelar_venda(venda, motivo="Cobrado em duplicidade no balcão", usuario_id=None)
    assert db.session.get(VendaBalcao, venda.id).status == "cancelada"


def test_cadastro_e_edicao_da_tabela(loja, client, monkeypatch):
    _login(monkeypatch, loja["owner"])
    casa_id = loja["casa"].id
    resposta = client.post(
        f"/casa-de-racao/{casa_id}/planos/tosa",
        data={
            "name": "Banho porte médio", "service_type": "banho", "price": "70", "sessions_per_month": "3",
            "cobranca": "avulso", "peso_min_kg": "20", "peso_max_kg": "30",
        },
    )
    assert resposta.status_code == 302
    plano = GroomingPlan.query.filter_by(name="Banho porte médio").one()
    assert plano.avulso and plano.sessions_per_month == 1
    assert plano.porte_label == "De 20 a 30 kg"

    pagina = client.get(f"/casa-de-racao/{casa_id}/planos/tosa").get_data(as_text=True)
    assert "De 20 a 30 kg" in pagina and "/sessão" in pagina
    assert client.get(f"/casa-de-racao/{casa_id}/planos/tosa/{plano.id}/editar").status_code == 200
    resposta = client.post(
        f"/casa-de-racao/{casa_id}/planos/tosa/{plano.id}/editar",
        data={
            "name": "Banho e tosa porte médio", "service_type": "banho_e_tosa", "price": "80",
            "sessions_per_month": "1", "cobranca": "avulso", "peso_min_kg": "20", "peso_max_kg": "30",
        },
    )
    assert resposta.status_code == 302
    db.session.refresh(plano)
    assert plano.name == "Banho e tosa porte médio" and plano.price == Decimal("80")
    # Faixa invertida é recusada.
    resposta = client.post(
        f"/casa-de-racao/{casa_id}/planos/tosa/{plano.id}/editar",
        data={"name": "x", "service_type": "banho", "price": "80", "sessions_per_month": "1",
              "cobranca": "avulso", "peso_min_kg": "30", "peso_max_kg": "20"},
    )
    assert resposta.status_code == 200 and "maior que o mínimo" in resposta.get_data(as_text=True)


def test_agenda_da_loja(loja, client, monkeypatch):
    _login(monkeypatch, loja["owner"])
    casa_id = loja["casa"].id
    pagina = client.get(f"/casa-de-racao/{casa_id}/banho-tosa?dia=2026-11-05").get_data(as_text=True)
    assert "Mel" in pagina and "Thor" in pagina
    resposta = client.post(
        f"/casa-de-racao/{casa_id}/banho-tosa/agendar",
        data={"animal_id": loja["thor"].id, "plan_id": loja["grande"].id, "data": "2026-11-05", "hora": "14:30"},
    )
    assert resposta.status_code == 302 and "dia=2026-11-05" in resposta.headers["Location"]
    sessao = GroomingSessao.query.one()
    assert sessao.valor == Decimal("120")
    pagina = client.get(f"/casa-de-racao/{casa_id}/banho-tosa?dia=2026-11-05").get_data(as_text=True)
    assert "Banho porte grande" in pagina and "Receber no caixa" not in pagina  # caixa fechado

    pdv.abrir_caixa(casa_id, valor_abertura="0", usuario_id=loja["owner"].id)
    assert "Receber no caixa" in client.get(f"/casa-de-racao/{casa_id}/banho-tosa?dia=2026-11-05").get_data(as_text=True)
    resposta = client.post(
        f"/casa-de-racao/{casa_id}/banho-tosa/{sessao.id}/cobrar",
        data={"t_pag": "20", "valor": "120,00", "dia": "2026-11-05"},
    )
    assert resposta.status_code == 302
    db.session.refresh(sessao)
    assert sessao.status == "realizado" and sessao.venda_id

    outra = banho_tosa.agendar(loja["casa"], animal_id=loja["mel"].id, plan_id=loja["pequeno"].id, quando=_quando())
    assert client.post(
        f"/casa-de-racao/{casa_id}/banho-tosa/{outra.id}/status", data={"status": "faltou"}
    ).status_code == 302
    db.session.refresh(outra)
    assert outra.status == "faltou"

    _login(monkeypatch, loja["outro"])
    assert client.get(f"/casa-de-racao/{casa_id}/banho-tosa").status_code == 404
    assert client.post(f"/casa-de-racao/{casa_id}/banho-tosa/{outra.id}/status", data={"status": "realizado"}).status_code == 404


def test_pagina_publica_mostra_porte_e_avulso(loja, client, monkeypatch):
    _login(monkeypatch, loja["tutor"])
    pagina = client.get("/planos/tosa").get_data(as_text=True)
    assert "Até 10 kg" in pagina and "serve para Mel" in pagina
    assert "/sessão" in pagina and "Agendar pelo WhatsApp" in pagina and "wa.me/5516998580506" in pagina
    resposta = client.get(f"/planos/tosa/{loja['pequeno'].id}/assinar")
    assert resposta.status_code == 302, "serviço avulso não vira assinatura"


def test_assinar_plano_mensal_de_loja_nao_quebra(loja, client, monkeypatch):
    """Antes, o motivo do Mercado Pago usava plan.clinica.nome e quebrava em plano de loja."""
    import blueprints.planos as planos_module

    capturado = {}

    class FakePreapproval:
        def create(self, dados):
            capturado.update(dados)
            return {"status": 201, "response": {"id": "pre-1", "init_point": "https://mp.example/init"}}

    class FakeSDK:
        def preapproval(self):
            return FakePreapproval()

    monkeypatch.setattr(planos_module, "mp_sdk", lambda: FakeSDK(), raising=False)
    _login(monkeypatch, loja["tutor"])
    resposta = client.post(
        f"/planos/tosa/{loja['pacote'].id}/assinar",
        data={"animal_id": loja["mel"].id, "consent": "y"},
    )
    assert resposta.status_code == 302 and resposta.headers["Location"] == "https://mp.example/init"
    assert "Cat Dog" in capturado["reason"]
