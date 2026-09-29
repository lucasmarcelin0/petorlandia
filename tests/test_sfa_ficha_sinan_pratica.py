"""Ficha SINAN mais rápida no dia a dia, sem mudar o que é gravado.

- Sinais clínicos e doenças pré-existentes: marca-se só o que está presente;
  o restante vira "2 - Não" (ou "9 - Ignorado" quando não deu para perguntar).
- Exames: primeiro escolhe-se o que foi coletado; só esses pedem data e
  resultado, e os demais ficam como "4 - Não realizado".
- Datas em dd/mm/aaaa em todas as páginas do SFA com formulário.
"""
import re
from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

from services import sfa_simulacao
from services.sfa_pre_t0 import (EXAMES_LABORATORIAIS, NENHUM_EXAME, carregar_esquema_pre_t0,
                                 coletar_respostas_pre_t0)

RAIZ = Path(__file__).resolve().parents[1]


def _base(**extra):
    dados = MultiDict([
        ("ficha_sinan", "1234567"), ("tipo_notificacao", "2"), ("agravo", "1"),
        ("data_notificacao", "2026-09-22"), ("data_inicio_sintomas", "2026-09-20"), ("nome", "Fictício"),
        ("sinais_clinicos__modo", "positivos"), ("doencas_preexistentes__modo", "positivos"),
    ])
    for chave, valor in extra.items():
        if isinstance(valor, list):
            dados.setlist(chave, valor)
        else:
            dados[chave] = valor
    return dados


@pytest.fixture
def schema(app):
    return carregar_esquema_pre_t0()


def test_marcar_so_os_presentes_grava_os_demais_como_nao(schema):
    respostas = coletar_respostas_pre_t0(_base(sinais_clinicos__febre="1", sinais_clinicos__cefaleia="1"), schema)
    sinais = respostas["sinais_clinicos"]
    assert sinais["febre"] == "1" and sinais["cefaleia"] == "1"
    assert sinais["exantema"] == "2" and sinais["dor_retroorbital"] == "2"
    assert len(sinais) == 14
    assert set(respostas["doencas_preexistentes"].values()) == {"2"}


def test_nao_foi_possivel_perguntar_vira_ignorado_so_onde_a_ficha_preve(schema):
    respostas = coletar_respostas_pre_t0(_base(
        doencas_preexistentes__diabetes="1", doencas_preexistentes__ignorado="1",
        sinais_clinicos__ignorado="1"), schema)
    comorbidades = respostas["doencas_preexistentes"]
    assert comorbidades["diabetes"] == "1"
    assert comorbidades["hipertensao_arterial"] == "9"
    # O campo 33 só tem Sim/Não na ficha: "ignorado" não se aplica.
    assert set(respostas["sinais_clinicos"].values()) == {"2"}


def test_modo_antigo_e_valores_invalidos(schema):
    antigo = MultiDict([(k, v) for k, v in _base().items(multi=True) if not k.endswith("__modo")])
    antigo["sinais_clinicos__febre"] = "2"
    assert coletar_respostas_pre_t0(antigo, schema)["sinais_clinicos"] == {"febre": "2"}
    with pytest.raises(ValueError):
        coletar_respostas_pre_t0(_base(sinais_clinicos__febre="2"), schema)


def test_exames_nao_marcados_ficam_como_nao_realizado(schema):
    respostas = coletar_respostas_pre_t0(_base(
        exames_realizados=["ns1"], ns1_data_coleta="2026-09-22", ns1_resultado="1",
        rt_pcr_data="2026-09-22", rt_pcr_resultado="2", sorotipo="2"), schema)
    assert respostas["exames_realizados"] == ["ns1"]
    assert respostas["ns1_data_coleta"] == "22/09/2026" and respostas["ns1_resultado"] == "1"
    # Desmarcado depois de preencher: o que ficou escondido não vale.
    assert respostas["rt_pcr_data"] == "" and respostas["rt_pcr_resultado"] == "4" and respostas["sorotipo"] == ""
    assert respostas["dengue_igm_resultado"] == "4" and respostas["histopatologia_resultado"] == "4"
    assert respostas["prnt_resultado"] == {"amostras": [], "resultado": "4"}


def test_rt_pcr_mantem_sorotipo_e_nenhum_exame_e_explicito(schema):
    com_pcr = coletar_respostas_pre_t0(_base(exames_realizados=["rt_pcr"], rt_pcr_resultado="1", sorotipo="2"), schema)
    assert com_pcr["sorotipo"] == "2" and com_pcr["ns1_resultado"] == "4"

    nenhum = coletar_respostas_pre_t0(_base(exames_realizados=[NENHUM_EXAME]), schema)
    assert nenhum["exames_realizados"] == [NENHUM_EXAME]
    assert nenhum["ns1_resultado"] == "4" and nenhum["rt_pcr_resultado"] == "4"

    # Sem resposta, nada é presumido.
    sem_resposta = coletar_respostas_pre_t0(_base(), schema)
    assert "exames_realizados" not in sem_resposta and sem_resposta["ns1_resultado"] == ""

    for invalido in (["ns1", NENHUM_EXAME], ["hemograma"]):
        with pytest.raises(ValueError):
            coletar_respostas_pre_t0(_base(exames_realizados=invalido), schema)


def test_ficha_renderiza_atalhos_na_ordem_da_rotina(client):
    texto = client.get("/sfa/pre-t0").get_data(as_text=True)
    assert 'name="sinais_clinicos__modo" value="positivos"' in texto
    assert 'type="checkbox" name="sinais_clinicos__febre" value="1"' in texto
    assert 'name="doencas_preexistentes__ignorado"' in texto
    assert 'name="sinais_clinicos__ignorado"' not in texto
    assert 'data-exames="ns1"' in texto and 'data-exames="rt_pcr isolamento"' in texto
    ordem = [texto.index(f'name="exames_realizados" value="{exame["id"]}"') for exame in EXAMES_LABORATORIAIS]
    assert ordem == sorted(ordem) and EXAMES_LABORATORIAIS[0]["id"] == "ns1" and EXAMES_LABORATORIAIS[1]["id"] == "rt_pcr"
    assert "js/date_br.js" in texto


def test_analise_da_simulacao_mostra_exames_coletados(app):
    variaveis = {var["id"]: var for var in sfa_simulacao.variaveis_etapa("sinan")}
    exames = variaveis["exames_realizados"]
    assert exames["tipo"] == "multipla"
    assert [valor for valor, _ in exames["opcoes"]][:2] == ["ns1", "rt_pcr"]


def test_toda_pagina_do_sfa_com_formulario_mostra_datas_em_dd_mm_aaaa():
    """Guarda do SFA: o campo de data nativo segue o idioma do navegador
    (mm/dd/aaaa em inglês). Toda página com formulário precisa do date_br.js,
    direto ou pelo layout que ela estende."""
    raiz = RAIZ / "templates"
    extends = re.compile(r"{%-?\s*extends\s+['\"]([^'\"]+)['\"]")
    include = re.compile(r"{%-?\s*include\s+['\"]([^'\"]+)['\"]")
    campo = re.compile(r"<(input|select|textarea)\b|<form\b", re.IGNORECASE)

    def texto(rel):
        caminho = raiz / rel
        return caminho.read_text(encoding="utf-8", errors="ignore") if caminho.exists() else ""

    def documento(rel):
        achado = extends.search(texto(rel))
        return documento(achado.group(1)) if achado else rel

    def tem_campo(rel, profundidade=0):
        conteudo = texto(rel)
        return bool(campo.search(conteudo)) or (
            profundidade < 4 and any(tem_campo(i, profundidade + 1) for i in include.findall(conteudo)))

    faltando = []
    for arquivo in sorted((raiz / "sfa").glob("*.html")):
        rel = arquivo.relative_to(raiz).as_posix()
        if arquivo.name.startswith("_") or not tem_campo(rel):
            continue
        if "js/date_br.js" not in texto(documento(rel)):
            faltando.append(f"{rel} (layout {documento(rel)})")
    assert not faltando, "Página do SFA sem static/js/date_br.js: " + ", ".join(faltando)


# ---------------------------------------------------------------------------
# Dados de preenchimento salvos na conta
# ---------------------------------------------------------------------------

def _login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _ficha_real(numero, **extra):
    dados = {
        "ficha_sinan": numero, "tipo_notificacao": "2", "agravo": "1", "data_notificacao": "2026-09-22",
        "data_inicio_sintomas": "2026-09-20", "nome": "Paciente Fictício",
        "uf_notificacao": "sp", "municipio_notificacao": "Orlândia", "codigo_municipio_notificacao": "3534302",
        "unidade_notificante": "UBS Central", "codigo_unidade_notificante": "1234",
        "investigador__municipio_unidade": "Orlândia / UBS Central", "investigador__codigo_unidade": "01",
        "investigador__nome": "Enfermeira Teste", "investigador__funcao": "Enfermeira",
        "investigador__assinatura": "Enfermeira Teste",
    }
    dados.update(extra)
    return dados


def test_unidade_municipio_e_investigador_ficam_salvos_na_conta(app, client):
    from extensions import db
    from models import User
    from services.sfa_pre_t0 import carregar_padrao_usuario

    usuario = User(name="Enfermeira", email="enf-sfa@test", password_hash="x", role="admin")
    db.session.add(usuario)
    db.session.commit()
    _login(client, usuario.id)

    primeira = client.get("/sfa/pre-t0").get_data(as_text=True)
    assert 'name="lembrar_padrao" value="1" checked' in primeira
    assert "Dados salvos da sua conta" not in primeira

    assert client.post("/sfa/pre-t0", data=_ficha_real("5550001", lembrar_padrao="1")).status_code == 200
    salvos = carregar_padrao_usuario(usuario.id)
    assert salvos["unidade_notificante"] == "UBS Central" and salvos["uf_notificacao"] == "SP"
    assert salvos["investigador__nome"] == "Enfermeira Teste"
    assert "investigador__assinatura" not in salvos and "nome" not in salvos

    segunda = client.get("/sfa/pre-t0").get_data(as_text=True)
    assert "Dados salvos da sua conta" in segunda
    assert 'value="UBS Central"' in segunda and 'value="3534302"' in segunda
    # A assinatura é sempre digitada: o campo volta vazio.
    assert re.search(r'name="investigador__assinatura"[^>]*value=""', segunda)
    assert 'value="Enfermeira Teste"' in segunda  # nome do investigador, este sim salvo

    # Desmarcar a opção apaga os dados salvos.
    assert client.post("/sfa/pre-t0", data=_ficha_real("5550002")).status_code == 200
    assert carregar_padrao_usuario(usuario.id) == {}


def test_sem_conta_logada_nao_oferece_lembrar(client):
    assert 'name="lembrar_padrao"' not in client.get("/sfa/pre-t0").get_data(as_text=True)


# ---------------------------------------------------------------------------
# CEP preenchendo o endereço
# ---------------------------------------------------------------------------

class _RespostaFalsa:
    def __init__(self, status_code, dados):
        self.status_code, self._dados = status_code, dados

    def json(self):
        return self._dados


@pytest.fixture
def viacep(monkeypatch):
    import requests
    from services import sfa_cep

    sfa_cep._cache.clear()
    chamadas, respostas = [], {}

    def falso_get(url, **kwargs):
        chamadas.append(url)
        resposta = respostas.get(url)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta or _RespostaFalsa(200, {"erro": "true"})

    monkeypatch.setattr(requests, "get", falso_get)
    return chamadas, respostas


def test_cep_preenche_endereco_e_so_o_cep_sai_do_servidor(client, viacep):
    import requests

    chamadas, respostas = viacep
    respostas["https://viacep.com.br/ws/14620000/json/"] = _RespostaFalsa(200, {
        "cep": "14620-000", "logradouro": "Rua Um", "bairro": "Centro", "localidade": "Orlândia",
        "uf": "SP", "ibge": "3534302"})
    resposta = client.get("/sfa/cep/14620-000.json")
    assert resposta.status_code == 200
    assert resposta.get_json()["endereco"] == {
        "cep": "14620000", "uf": "SP", "municipio": "Orlândia", "codigo_ibge": "3534302",
        "bairro": "Centro", "logradouro": "Rua Um"}
    client.get("/sfa/cep/14620000.json")
    assert chamadas == ["https://viacep.com.br/ws/14620000/json/"]  # a segunda veio do cache

    assert client.get("/sfa/cep/123.json").status_code == 400
    assert client.get("/sfa/cep/99999999.json").status_code == 404
    respostas["https://viacep.com.br/ws/11111111/json/"] = requests.ConnectionError("sem rede")
    fora_do_ar = client.get("/sfa/cep/11111111.json")
    assert fora_do_ar.status_code == 503 and "à mão" in fora_do_ar.get_json()["motivo"]


def test_ficha_pede_o_cep_antes_do_endereco(client):
    texto = client.get("/sfa/pre-t0").get_data(as_text=True)
    assert 'data-cep-url="/sfa/cep/00000000.json"' in texto
    assert "data-cep-status" in texto
    assert texto.index('data-field-card="cep"') < texto.index('data-field-card="logradouro"')
    assert texto.index('data-field-card="cep"') < texto.index('data-field-card="uf_residencia"')


def test_cep_e_cartao_sus_aceitam_hifen_ponto_e_espaco(schema):
    respostas = coletar_respostas_pre_t0(_base(cep="14620-000", cartao_sus="123 4567 8901 2345"), schema)
    assert respostas["cep"] == "14620000" and respostas["cartao_sus"] == "123456789012345"
    with pytest.raises(ValueError):
        coletar_respostas_pre_t0(_base(cep="1462A-000"), schema)
