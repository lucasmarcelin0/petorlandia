"""Campos que a ficha SINAN exige no envio (pré-T0, área das unidades e simulação)."""
import pytest
from bs4 import BeautifulSoup
from flask import render_template
from werkzeug.datastructures import MultiDict

from services.sfa_pre_t0 import FIELD_SPECS, CampoInvalido, carregar_esquema_pre_t0, coletar_respostas_pre_t0

SINAIS = [item for item, _rotulo in FIELD_SPECS["33"]["items"]]
DOENCAS = [item for item, _rotulo in FIELD_SPECS["34"]["items"]]

# Além de agravo, datas da notificação e dos sintomas e nome, que já eram exigidos.
OBRIGATORIOS = {
    "data_nascimento": "1990-05-04", "sexo": "F", "gestante": "5", "raca_cor": "4",
    "nome_mae": "Joana da Silva", "logradouro": "Rua Um", "numero_residencia": "100",
    "telefone": "16991112222", "zona": "1", "ocupacao": "Professora", "hospitalizacao": "2",
    "caso_autoctone": "1", "sinais_alarme": "2", "dengue_grave": "2",
    **{f"sinais_clinicos__{item}": "1" if item == "febre" else "2" for item in SINAIS},
    **{f"doencas_preexistentes__{item}": "2" for item in DOENCAS},
}


def _form(**extra):
    dados = {"ficha_sinan": "2985999", "agravo": "1", "data_notificacao": "2026-10-12",
             "data_inicio_sintomas": "2026-10-10", "nome": "Maria Paciente", **OBRIGATORIOS}
    dados.update(extra)
    return MultiDict(dados)


def _erro(**extra):
    with pytest.raises(CampoInvalido) as erro:
        coletar_respostas_pre_t0(_form(**extra))
    return erro.value.campo


def test_ficha_com_os_campos_obrigatorios_e_aceita(app):
    with app.app_context():
        respostas = coletar_respostas_pre_t0(_form())
    assert respostas["nome_mae"] == "Joana da Silva" and respostas["numero_residencia"] == "100"
    assert respostas["sinais_clinicos"] == {item: "1" if item == "febre" else "2" for item in SINAIS}
    assert respostas["sinais_alarme"]["status"] == "2" and respostas["dengue_grave"]["status"] == "2"
    assert respostas["doencas_preexistentes"] == {item: "2" for item in DOENCAS}


@pytest.mark.parametrize("campo", ["data_nascimento", "sexo", "gestante", "raca_cor", "nome_mae", "logradouro",
                                   "numero_residencia", "telefone", "zona", "ocupacao", "hospitalizacao",
                                   "caso_autoctone", "sinais_alarme", "dengue_grave"])
def test_cada_campo_obrigatorio_em_branco_e_apontado(app, campo):
    with app.app_context():
        assert _erro(**{campo: ""}) == campo


def test_idade_sozinha_nao_substitui_a_data_de_nascimento(app):
    # Na tela, digitar a idade já preenche a data estimada; sem ela o envio é recusado.
    with app.app_context():
        assert _erro(data_nascimento="", idade_valor="36", idade_unidade="4") == "data_nascimento"


def test_gestante_nao_e_exigida_do_sexo_masculino(app):
    with app.app_context():
        assert coletar_respostas_pre_t0(_form(sexo="M", gestante=""))["gestante"] == ""
        assert coletar_respostas_pre_t0(_form(sexo="M", gestante="6"))["gestante"] == "6"
        assert _erro(sexo="I", gestante="") == "gestante"


def test_sinais_clinicos_precisam_de_todos_os_itens_e_aceitam_ignorado(app):
    with app.app_context():
        assert _erro(sinais_clinicos__mialgia="") == "sinais_clinicos__mialgia"
        respostas = coletar_respostas_pre_t0(_form(sinais_clinicos__febre="2", sinais_clinicos__cefaleia="9"))
    assert respostas["sinais_clinicos"]["febre"] == "2" and respostas["sinais_clinicos"]["cefaleia"] == "9"


def test_doencas_preexistentes_precisam_de_todos_os_itens(app):
    with app.app_context():
        assert _erro(doencas_preexistentes__hepatopatias="") == "doencas_preexistentes__hepatopatias"
        respostas = coletar_respostas_pre_t0(_form(doencas_preexistentes__diabetes="1",
                                                   doencas_preexistentes__hepatopatias="9"))
    assert respostas["doencas_preexistentes"]["diabetes"] == "1"
    assert respostas["doencas_preexistentes"]["hepatopatias"] == "9"


def test_ns1_com_data_exige_resultado(app):
    with app.app_context():
        assert _erro(ns1_data_coleta="2026-10-11") == "ns1_resultado"
        com_resultado = coletar_respostas_pre_t0(_form(ns1_data_coleta="2026-10-11", ns1_resultado="2"))
        sem_exame = coletar_respostas_pre_t0(_form())
        # Resultado sem a data continua aceito (fica em "O que ainda falta").
        sem_data = coletar_respostas_pre_t0(_form(ns1_resultado="1"))
    assert (com_resultado["ns1_data_coleta"], com_resultado["ns1_resultado"]) == ("11/10/2026", "2")
    assert (sem_exame["ns1_data_coleta"], sem_exame["ns1_resultado"]) == ("", "")
    assert sem_data["ns1_resultado"] == "1"


def test_demais_campos_continuam_opcionais(app):
    # Na residência (etapa 4) só logradouro, número, telefone e zona são exigidos.
    opcionais = ("ficha_sinan", "escolaridade", "cartao_sus", "uf_residencia", "municipio_residencia", "bairro",
                 "distrito_residencia", "complemento", "ponto_referencia", "cep", "pais_residencia",
                 "data_investigacao", "classificacao", "criterio_confirmacao", "evolucao_caso", "data_encerramento")
    with app.app_context():
        respostas = coletar_respostas_pre_t0(_form(**{campo: "" for campo in opcionais}))
    assert all((respostas[campo]["valor"] if isinstance(respostas[campo], dict) else respostas[campo]) == ""
               for campo in opcionais)


def _pagina(app, submitted=None):
    with app.test_request_context("/x"):
        html = render_template("sfa/pre_t0_form.html", schema=carregar_esquema_pre_t0(), error="", error_field="",
                               submitted=MultiDict(submitted or {}), form_action="/x")
    return BeautifulSoup(html, "html.parser")


def test_tela_marca_os_obrigatorios_e_traz_doencas_como_nao(app):
    pagina = _pagina(app)

    def marca(chave):
        selo = pagina.select_one(f"#campo-{chave} .required-mark")
        return selo.get_text(strip=True) if selo else ""

    for chave in ("data_nascimento", "sexo", "gestante", "raca_cor", "nome_mae", "logradouro", "numero_residencia",
                  "telefone", "zona", "ocupacao", "sinais_clinicos", "doencas_preexistentes", "hospitalizacao",
                  "caso_autoctone", "sinais_alarme", "dengue_grave"):
        assert marca(chave) == "Obrigatório", chave
    assert marca("ns1_resultado") == "Obrigatório se houver data"
    # Etapa 4 (residência): fora 21, 22, 28 e 29, nada é obrigatório.
    for chave in ("uf_residencia", "municipio_residencia", "distrito_residencia", "bairro", "complemento",
                  "ponto_referencia", "cep", "pais_residencia", "escolaridade", "ficha_sinan", "classificacao"):
        assert marca(chave) == "", chave

    assert pagina.select_one("#campo-ns1_resultado")["data-required-with"] == "ns1_data_coleta"
    for chave in ("logradouro", "numero_residencia", "telefone", "nome_mae", "ocupacao", "data_nascimento"):
        assert pagina.select_one(f"#input-{chave}").has_attr("required"), chave
    for chave in ("municipio_residencia", "bairro", "codigo_logradouro"):
        assert not pagina.select_one(f"#input-{chave}").has_attr("required"), chave
    for chave in ("zona", "caso_autoctone", "sinais_alarme", "dengue_grave"):
        assert pagina.select_one(f'input[name="{chave}"][required]'), chave
    assert "S/N" in pagina.select_one("#dica-numero_residencia").get_text()
    assert "SEM TELEFONE" in pagina.select_one("#dica-telefone").get_text()
    assert pagina.select_one("#input-ocupacao")["list"] == "sugestoes-ocupacao"

    # Sinais clínicos e doenças pré-existentes: "Não" marcado, com Sim e Ignorado para trocar.
    for chave, itens in (("sinais_clinicos", SINAIS), ("doencas_preexistentes", DOENCAS)):
        for item in itens:
            opcoes = pagina.select(f'input[name="{chave}__{item}"]')
            assert [(o["type"], o["value"]) for o in opcoes] == [("radio", "1"), ("radio", "2"), ("radio", "9")], item
            assert [o["value"] for o in opcoes if o.has_attr("checked")] == ["2"], item


def test_resposta_enviada_prevalece_sobre_o_nao_pre_marcado(app):
    pagina = _pagina(app, {"doencas_preexistentes__diabetes": "1", "sinais_clinicos__febre": "1",
                           "sinais_clinicos__cefaleia": "9"})
    assert pagina.select_one('input[name="doencas_preexistentes__diabetes"][checked]')["value"] == "1"
    assert pagina.select_one('input[name="doencas_preexistentes__hepatopatias"][checked]')["value"] == "2"
    assert pagina.select_one('input[name="sinais_clinicos__febre"][checked]')["value"] == "1"
    assert pagina.select_one('input[name="sinais_clinicos__cefaleia"][checked]')["value"] == "9"
    assert pagina.select_one('input[name="sinais_clinicos__mialgia"][checked]')["value"] == "2"
