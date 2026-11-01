"""Operador da loja: o dono libera alguém para o dia a dia e desliga quando quiser."""
from __future__ import annotations

from types import SimpleNamespace

import flask_login.utils as login_utils
import pytest

from extensions import db
from models import CaixaSessao, CasaDeRacao, LojaMembro, Product, ProductVariant, User, VendaBalcao
from services.workspaces import resolve_experience

GTIN = "7891000315507"


@pytest.fixture()
def loja(app):
    owner = User(name="Renato", email="renato-op@example.com")
    owner.set_password("x")
    operador = User(name="Carla Souza", email="carla-op@example.com", phone="+5516991110000")
    operador.set_password("x")
    estranho = User(name="Estranho", email="estranho-op@example.com")
    estranho.set_password("x")
    db.session.add_all([owner, operador, estranho])
    db.session.flush()
    casa = CasaDeRacao(nome="Cat Dog", tipo="petshop", owner_id=owner.id, status="ativa")
    db.session.add(casa)
    db.session.flush()
    racao = Product(name="Ração Premium", price=150.0, stock=10, casa_de_racao_id=casa.id, ncm="23091000")
    racao.variants.append(ProductVariant(name="15 kg", price=150.0, stock=10, barcode=GTIN, status="active"))
    db.session.add(racao)
    membro = LojaMembro(casa_de_racao_id=casa.id, user_id=operador.id, created_by_id=owner.id)
    db.session.add(membro)
    db.session.commit()
    return {"casa": casa, "owner": owner, "operador": operador, "estranho": estranho, "racao": racao,
            "membro": membro}


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def test_operador_usa_o_dia_a_dia(loja, client, monkeypatch):
    _login(monkeypatch, loja["operador"])
    casa_id = loja["casa"].id
    pagina = client.get(f"/casa-de-racao/{casa_id}/caixa").get_data(as_text=True)
    assert "Abrir o caixa" in pagina and "Banho e tosa" in pagina and "Notas" in pagina
    assert f"/casa-de-racao/{casa_id}/fiscal\"" not in pagina and "Painel da loja" not in pagina
    assert client.post(f"/casa-de-racao/{casa_id}/caixa/abrir", data={"valor_abertura": "50"}).status_code == 302
    assert CaixaSessao.query.one().aberto_por_id == loja["operador"].id

    corpo = {
        "chave": "venda-operador-1",
        "itens": [{"product_id": loja["racao"].id, "variant_id": loja["racao"].variants[0].id, "quantidade": "1"}],
        "pagamentos": [{"t_pag": "01", "valor": "150"}],
    }
    resposta = client.post(f"/casa-de-racao/{casa_id}/caixa/venda", json=corpo).get_json()
    assert resposta["ok"]
    assert db.session.get(VendaBalcao, resposta["venda_id"]).created_by_id == loja["operador"].id

    for caminho in (
        "caixa/vendas", "estoque", f"estoque/produto/{loja['racao'].id}", "estoque/entradas", "nfce",
        "banho-tosa", "tutores", "animais", "produtos", "vendas",
    ):
        assert client.get(f"/casa-de-racao/{casa_id}/{caminho}").status_code == 200, caminho

    estoque = client.get(f"/casa-de-racao/{casa_id}/estoque").get_data(as_text=True)
    assert "Importar planilha" not in estoque
    entradas = client.get(f"/casa-de-racao/{casa_id}/estoque/entradas").get_data(as_text=True)
    assert "ciencia_automatica" not in entradas
    agenda = client.get(f"/casa-de-racao/{casa_id}/banho-tosa").get_data(as_text=True)
    assert "Tabela de preços e planos" not in agenda and f'href="/casa-de-racao/{casa_id}/caixa"' in agenda


@pytest.mark.parametrize(
    "metodo, caminho",
    [
        ("get", ""),  # painel do dono
        ("get", "fiscal"),
        ("post", "fiscal/certificado"),
        ("post", "fiscal/ambiente"),
        ("post", "nfce/inutilizar"),
        ("get", "nfce/xmls?mes=2026-11"),
        ("get", "estoque/importar-produtos"),
        ("post", "estoque/entradas/sefaz/automatico"),
        ("get", "planos/tosa"),
        ("post", "mercado-pago/desconectar"),
        ("get", "equipe"),
        ("post", "equipe"),
    ],
)
def test_operador_nao_mexe_no_que_e_do_dono(loja, client, monkeypatch, metodo, caminho):
    _login(monkeypatch, loja["operador"])
    url = f"/casa-de-racao/{loja['casa'].id}" + (f"/{caminho}" if caminho else "")
    assert getattr(client, metodo)(url).status_code == 404


def test_acesso_desligado_e_quem_nao_e_da_equipe(loja, client, monkeypatch):
    casa_id = loja["casa"].id
    _login(monkeypatch, loja["estranho"])
    assert client.get(f"/casa-de-racao/{casa_id}/caixa").status_code == 404

    loja["membro"].ativo = False
    db.session.commit()
    _login(monkeypatch, loja["operador"])
    for caminho in ("caixa", "estoque", "banho-tosa", "tutores", "produtos"):
        assert client.get(f"/casa-de-racao/{casa_id}/{caminho}").status_code == 404, caminho


def test_dono_libera_desliga_e_religa(loja, client, monkeypatch):
    import blueprints.loja_equipe as equipe_bp

    enviados = []
    monkeypatch.setattr(equipe_bp, "_enviar_email", lambda para, assunto, corpo: enviados.append((para, corpo)) or True)
    _login(monkeypatch, loja["owner"])
    casa_id = loja["casa"].id
    url = f"/casa-de-racao/{casa_id}/equipe"
    pagina = client.get(url).get_data(as_text=True)
    assert "Carla Souza" in pagina and "acesso ligado" in pagina and "Desligar acesso" in pagina

    # Pessoa nova: conta criada e link para criar a senha, que leva ao caixa.
    resposta = client.post(url, data={"nome": "João Lima", "email": "Joao.Lima@Example.com", "celular": "(16) 99222-3344"})
    assert resposta.status_code == 302
    joao = User.query.filter_by(email="joao.lima@example.com").one()
    assert joao.casa_de_racao_id is None, "operador não vira cliente da loja"
    assert LojaMembro.query.filter_by(casa_de_racao_id=casa_id, user_id=joao.id, ativo=True).one()
    para, corpo = enviados[-1]
    assert para == "joao.lima@example.com"
    assert "/primeiro-acesso?" in corpo and "token=" in corpo and "caixa" in corpo

    # Conta que já existe: basta o e-mail.
    assert client.post(url, data={"email": "estranho-op@example.com"}).status_code == 302
    assert LojaMembro.query.filter_by(user_id=loja["estranho"].id, ativo=True).one()

    # Erros: e-mail inválido, e-mail do dono, pessoa nova sem celular, celular de outra conta.
    total = LojaMembro.query.count()
    client.post(url, data={"email": "sem-arroba"})
    client.post(url, data={"email": "renato-op@example.com"})
    client.post(url, data={"nome": "Sem Celular", "email": "sem-celular@example.com"})
    client.post(url, data={"nome": "Outro", "email": "outro-op@example.com", "celular": "(16) 99111-0000"})
    assert LojaMembro.query.count() == total
    assert User.query.filter_by(email="sem-celular@example.com").count() == 0

    # Desliga e religa: o acesso e o menu do operador acompanham na hora.
    from context_processors import _get_cached_context, _set_cached_context

    membro = loja["membro"]
    _set_cached_context(loja["operador"].id, "loja_operada", {"id": casa_id, "nome": "Cat Dog"})
    assert client.post(f"{url}/{membro.id}/acesso", data={"ativo": "0"}).status_code == 302
    assert _get_cached_context(loja["operador"].id, "loja_operada") is None
    db.session.refresh(membro)
    assert membro.ativo is False and membro.desativado_em is not None
    _login(monkeypatch, loja["operador"])
    assert client.get(f"/casa-de-racao/{casa_id}/caixa").status_code == 404
    _login(monkeypatch, loja["owner"])
    client.post(f"{url}/{membro.id}/acesso", data={"ativo": "1"})
    _login(monkeypatch, loja["operador"])
    assert client.get(f"/casa-de-racao/{casa_id}/caixa").status_code == 200


def test_operador_novo_cria_a_senha_pelo_link_e_cai_no_caixa(loja, client, monkeypatch):
    from urllib.parse import urlsplit

    from flask_login import AnonymousUserMixin

    import blueprints.loja_equipe as equipe_bp

    enviados = []
    monkeypatch.setattr(equipe_bp, "_enviar_email", lambda para, assunto, corpo: enviados.append(corpo) or True)
    _login(monkeypatch, loja["owner"])
    casa_id = loja["casa"].id
    client.post(f"/casa-de-racao/{casa_id}/equipe",
                data={"nome": "João Lima", "email": "joao@example.com", "celular": "(16) 99222-3344"})
    link = urlsplit(next(linha for linha in enviados[-1].splitlines() if "/primeiro-acesso?" in linha))
    primeiro_acesso = f"{link.path}?{link.query}"

    _login(monkeypatch, AnonymousUserMixin())
    assert client.get(primeiro_acesso).status_code == 200
    resposta = client.post(primeiro_acesso, data={"phone": "(16) 99222-3344"})
    assert resposta.status_code == 302 and resposta.headers["Location"].endswith("/primeiro-acesso/senha")
    resposta = client.post("/primeiro-acesso/senha", data={
        "email": "joao@example.com", "password": "segredo123", "confirm_password": "segredo123",
    })
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith(f"/casa-de-racao/{casa_id}/caixa")
    assert User.query.filter_by(email="joao@example.com").one().check_password("segredo123")


def test_menu_do_operador_leva_ao_caixa(loja, app):
    casa = loja["casa"]
    with app.test_request_context():
        experiencia = resolve_experience(loja["operador"], loja_operada=SimpleNamespace(id=casa.id, nome=casa.nome))
        area = next(w for w in experiencia.workspaces if w.key == "store_operator")
        assert area.label == "Cat Dog"
        assert [a.label for a in area.actions] == ["Caixa", "Banho e tosa", "Estoque", "Produtos"]
        assert area.actions[0].url == f"/casa-de-racao/{casa.id}/caixa"
        # O dono não ganha um segundo menu para a própria loja.
        dono = resolve_experience(loja["owner"], store=casa, loja_operada=SimpleNamespace(id=casa.id, nome=casa.nome))
        assert "store_operator" not in {w.key for w in dono.workspaces}
