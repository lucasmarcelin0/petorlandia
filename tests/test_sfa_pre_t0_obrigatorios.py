"""Campos que a ficha SINAN exige no envio (pré-T0, área das unidades e simulação)."""
import pytest
from bs4 import BeautifulSoup
from flask import render_template
from werkzeug.datastructures import MultiDict

from services.sfa_pre_t0 import FIELD_SPECS, CampoInvalido, carregar_esquema_pre_t0, coletar_respostas_pre_t0

DOENCAS = [item for item, _rotulo in FIELD_SPECS["34"]["items"]]

# Além de agravo, datas da notificação e dos sintomas e nome, que já eram exigidos.
OBRIGATORIOS = {
    "data_nascimento": "1990-05-04", "sexo": "F", "gestante": "5", "raca_cor": "4",
    "nome_mae": "Joana da Silva", "municipio_residencia": "Orlândia", "bairro": "Centro",
    "logradouro": "Rua Um", "numero_residencia": "100", "ocupacao": "Professora",
    "sinais_clinicos__febre": "1", "hospitalizacao": "2",
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
    assert respostas["sinais_clinicos"]["febre"] == "1"
    assert respostas["doencas_preexistentes"] == {item: "2" for item in DOENCAS}


@pytest.mark.parametrize("campo", ["data_nascimento", "sexo", "gestante", "raca_cor", "nome_mae",
                                   "municipio_residencia", "bairro", "logradouro", "numero_residencia",
                                   "ocupacao", "hospitalizacao"])
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


def test_sinais_clinicos_pedem_pelo_menos_um_presente(app):
    with app.app_context():
        assert _erro(sinais_clinicos__febre="2") == "sinais_clinicos__febre"
        assert _erro(sinais_clinicos__febre="") == "sinais_clinicos__febre"
        respostas = coletar_respostas_pre_t0(_form(sinais_clinicos__febre="2", sinais_clinicos__cefaleia="1"))
    assert respostas["sinais_clinicos"] == {"febre": "2", "cefaleia": "1"}


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
    opcionais = ("ficha_sinan", "escolaridade", "cartao_sus", "uf_residencia", "distrito_residencia",
                 "complemento", "ponto_referencia", "cep", "telefone", "zona", "data_investigacao",
                 "caso_autoctone", "classificacao", "criterio_confirmacao", "evolucao_caso", "data_encerramento")
    with app.app_context():
        respostas = coletar_respostas_pre_t0(_form(**{campo: "" for campo in opcionais}))
    assert all(respostas[campo] == "" for campo in opcionais)


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

    for chave in ("data_nascimento", "sexo", "gestante", "raca_cor", "nome_mae", "municipio_residencia", "bairro",
                  "logradouro", "numero_residencia", "ocupacao", "sinais_clinicos", "doencas_preexistentes",
                  "hospitalizacao"):
        assert marca(chave) == "Obrigatório", chave
    assert marca("ns1_resultado") == "Obrigatório se houver data"
    for chave in ("caso_autoctone", "zona", "cep", "complemento", "escolaridade", "ficha_sinan"):
        assert marca(chave) == "", chave

    assert pagina.select_one("#campo-ns1_resultado")["data-required-with"] == "ns1_data_coleta"
    assert pagina.select_one("#campo-sinais_clinicos").has_attr("data-exige-marcado")
    for chave in ("municipio_residencia", "logradouro", "numero_residencia", "nome_mae", "ocupacao", "data_nascimento"):
        assert pagina.select_one(f"#input-{chave}").has_attr("required"), chave
    assert not pagina.select_one("#input-codigo_logradouro").has_attr("required")
    assert "S/N" in pagina.select_one("#dica-numero_residencia").get_text()
    assert pagina.select_one("#input-ocupacao")["list"] == "sugestoes-ocupacao"

    for item in DOENCAS:
        marcada = pagina.select_one(f'input[name="doencas_preexistentes__{item}"][checked]')
        assert marcada is not None and marcada["value"] == "2", item
    assert not pagina.select('input[name^="sinais_clinicos__"][type="checkbox"][checked]')


def test_resposta_enviada_prevalece_sobre_o_nao_pre_marcado(app):
    pagina = _pagina(app, {"doencas_preexistentes__diabetes": "1"})
    assert pagina.select_one('input[name="doencas_preexistentes__diabetes"][checked]')["value"] == "1"
    assert pagina.select_one('input[name="doencas_preexistentes__hepatopatias"][checked]')["value"] == "2"
