import pytest
from flask import render_template
from werkzeug.datastructures import MultiDict

from services.sfa_pre_t0 import CampoInvalido, carregar_esquema_pre_t0, coletar_respostas_pre_t0


def _form_valido(**extra):
    dados = {
        "ficha_sinan": "2985999",
        "agravo": "1",
        "data_notificacao": "2026-09-01",
        "data_inicio_sintomas": "2026-08-30",
        "nome": "Teste",
    }
    dados.update(extra)
    return MultiDict(dados)


def test_erro_numerico_informa_o_campo_para_correcao():
    with pytest.raises(CampoInvalido) as erro:
        coletar_respostas_pre_t0(_form_valido(cep="14620-abc"))
    assert erro.value.campo == "cep"
    assert isinstance(erro.value, ValueError)
    assert "somente números" in str(erro.value)


def test_erro_de_data_e_de_obrigatorio_informam_o_campo():
    with pytest.raises(CampoInvalido) as erro:
        coletar_respostas_pre_t0(_form_valido(data_nascimento="31/02/1990"))
    assert erro.value.campo == "data_nascimento"

    with pytest.raises(CampoInvalido) as erro:
        coletar_respostas_pre_t0(_form_valido(nome=""))
    assert erro.value.campo == "nome"


def test_idade_sem_unidade_aponta_a_unidade():
    with pytest.raises(CampoInvalido) as erro:
        coletar_respostas_pre_t0(_form_valido(idade_valor="30"))
    assert erro.value.campo == "idade_unidade"


def test_formulario_leva_campo_e_mensagem_para_o_navegador(app):
    schema = carregar_esquema_pre_t0()
    with app.test_request_context("/x"):
        html = render_template(
            "sfa/pre_t0_form.html", schema=schema, error="Confira os campos numéricos.",
            error_field="cep", submitted=MultiDict(), form_action="/x",
        )
    assert 'data-error-field="cep"' in html
    assert 'data-error-message="Confira os campos numéricos."' in html
