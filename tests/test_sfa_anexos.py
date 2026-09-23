import html
from pathlib import Path

import pytest
from flask import Flask, render_template

from blueprints.sfa import bp as sfa_bp
from services import sfa_service
from services.sfa_anexos import carregar_ficha_sinan_dengue, montar_anexos_protocolo

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Campos que o importador de fichas grava fora de dados_json (cadastro e log).
CHAVES_SINAN_FORA_DO_JSON = {
    "ficha_sinan", "n_caso", "nome", "data_nascimento", "telefone", "bairro", "endereco",
    "data_notificacao", "data_inicio_sintomas",
}


@pytest.fixture(scope="module")
def anexos():
    return montar_anexos_protocolo()


@pytest.fixture(scope="module")
def anexos_html(anexos):
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"))
    app.register_blueprint(sfa_bp)
    with app.test_request_context("/sfa/formularios/anexos"):
        return html.unescape(render_template("sfa/anexos_protocolo.html", **anexos))


def test_anexos_reproduzem_cada_pergunta_opcao_e_ajuda_do_site(anexos_html):
    for stage in ("t0", "t7", "t30"):
        schema = getattr(sfa_service, f"carregar_{stage}_form_schema")()
        for campo in sfa_service.iterar_campos_form(schema):
            assert campo["label"] in anexos_html, f"{stage}: pergunta ausente: {campo['key']}"
            for opcao in campo.get("options", []):
                assert opcao in anexos_html, f"{stage}: opcao ausente em {campo['key']}: {opcao}"
            if campo.get("help_text"):
                assert campo["help_text"] in anexos_html, f"{stage}: ajuda ausente em {campo['key']}"


def test_ficha_sinan_vem_antes_dos_formularios(anexos_html):
    posicoes = [
        anexos_html.index("ANEXO A"),
        anexos_html.index("Ficha SINAN — Ficha de Investigação Dengue e Febre de Chikungunya"),
        anexos_html.index("ANEXO B"),
        anexos_html.index("Formulário T0"),
        anexos_html.index("ANEXO C"),
        anexos_html.index("Formulário T7"),
        anexos_html.index("ANEXO D"),
        anexos_html.index("Formulário T30"),
    ]
    assert posicoes == sorted(posicoes)


def test_toda_pergunta_condicional_ganha_regra_com_numero(anexos):
    for form in anexos["formularios"]:
        numeros = [p["numero"] for s in form["secoes"] for p in s["perguntas"]]
        assert numeros == list(range(1, len(numeros) + 1))
        for secao in form["secoes"]:
            for pergunta in secao["perguntas"]:
                if "visible_if" not in pergunta:
                    assert pergunta["condicao"] is None
                    continue
                textos = [pergunta["condicao"]["texto"], *pergunta["condicao"]["itens"]]
                assert all('pergunta "' not in texto for texto in textos), (
                    f"{form['etapa']}: regra aponta para campo sem numero em {pergunta['key']}"
                )


def test_regras_do_t30_explicam_obito_e_sintomas(anexos):
    t30 = next(form for form in anexos["formularios"] if form["stage"] == "t30")
    perguntas = {p["key"]: p for s in t30["secoes"] for p in s["perguntas"]}
    obito = perguntas["situacao_participante"]["numero"]

    assert perguntas["estado_saude_final"]["condicao"]["texto"] == f'Não aparece se pergunta {obito} = "Faleceu".'
    assert perguntas["respondent_name"]["condicao"]["texto"] == (
        'Aparece se pergunta 1 respondida com opção diferente de "A propria pessoa".'
    )
    fonte = perguntas["fonte_ainda_ativa"]["condicao"]
    assert fonte["texto"] == "Aparece se ocorrer pelo menos uma destas situações:"
    assert any(item.startswith('no T7, "') for item in fonte["itens"])


def test_resumo_do_tcle_do_site_aparece_no_anexo_do_t0(anexos_html):
    assert "Resumo do Termo de Consentimento" in anexos_html
    assert "Sua participacao e voluntaria." in anexos_html


def test_ficha_sinan_so_marca_como_transcrito_o_que_a_plataforma_guarda():
    conhecidas = set(sfa_service.SINAN_STRUCTURED_FIELDS) | CHAVES_SINAN_FORA_DO_JSON
    for secao in carregar_ficha_sinan_dengue()["secoes"]:
        for campo in secao["campos"]:
            desconhecidas = set(campo.get("plataforma", [])) - conhecidas
            assert not desconhecidas, f"{campo['campo']}: chaves inexistentes {desconhecidas}"


def test_ficha_sinan_traz_os_71_campos_numerados_da_ficha_oficial(anexos_html):
    ficha = carregar_ficha_sinan_dengue()
    numeros = [
        campo["numero"]
        for secao in ficha["secoes"]
        for campo in secao["campos"]
        if campo["numero"].isdigit()
    ]
    assert numeros == [str(numero) for numero in range(1, 72)]
    assert ficha["versao"] in anexos_html
    for secao in ficha["secoes"]:
        for campo in secao["campos"]:
            assert campo["campo"] in anexos_html
