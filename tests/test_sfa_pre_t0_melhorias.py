import pytest
from flask import render_template
from werkzeug.datastructures import MultiDict

from services.sfa_pre_t0 import CampoInvalido, carregar_esquema_pre_t0, coletar_respostas_pre_t0


def _form(**extra):
    dados = {"ficha_sinan": "2985999", "agravo": "2", "data_notificacao": "2026-09-01",
             "data_inicio_sintomas": "2026-08-30", "nome": "Teste"}
    dados.update(extra)
    return MultiDict(dados)


def test_agravo_fica_na_primeira_pagina_ao_lado_do_numero_da_notificacao(app):
    with app.app_context():
        secoes = carregar_esquema_pre_t0()["sections"]
    assert [campo["key"] for campo in secoes[0]["fields"]] == ["ficha_sinan", "agravo"]
    assert all(campo["key"] != "agravo" for secao in secoes[1:] for campo in secao["fields"])


def test_campos_numericos_aceitam_separadores_do_preenchimento_automatico(app):
    with app.app_context():
        respostas = coletar_respostas_pre_t0(_form(cep="14620-000", cartao_sus="898 0011 2233 4455", ficha_sinan="2985-999"))
    assert respostas["cep"] == "14620000"
    assert respostas["cartao_sus"] == "898001122334455"
    assert respostas["ficha_sinan"] == "2985999"


def test_campo_numerico_com_letras_continua_sendo_recusado_e_aponta_o_campo(app):
    with app.app_context(), pytest.raises(CampoInvalido) as erro:
        coletar_respostas_pre_t0(_form(cep="14620-abc"))
    assert erro.value.campo == "cep"


def test_resultado_de_cada_exame_e_gravado_separadamente(app):
    with app.app_context():
        respostas = coletar_respostas_pre_t0(_form(
            prnt_resultado__res__s1="1", prnt_resultado__res__s2="2", prnt_resultado__res__prnt="3"))
    exames = respostas["prnt_resultado"]
    assert exames["resultados"] == {"s1": "1", "s2": "2", "prnt": "3"}
    assert exames["amostras"] == ["s1", "s2", "prnt"]
    assert exames["resultado"] == "3"  # compatibilidade: o exame mais conclusivo (PRNT)


def test_exame_sem_resultado_fica_de_fora_e_formato_antigo_continua_valendo(app):
    with app.app_context():
        so_s2 = coletar_respostas_pre_t0(_form(prnt_resultado__res__s2="1"))["prnt_resultado"]
        antigo = coletar_respostas_pre_t0(_form(prnt_resultado__s1="1", prnt_resultado="2"))["prnt_resultado"]
        vazio = coletar_respostas_pre_t0(_form())["prnt_resultado"]
    assert so_s2["resultados"] == {"s2": "1"} and so_s2["amostras"] == ["s2"]
    assert antigo == {"amostras": ["s1"], "resultado": "2", "resultados": {}}
    assert vazio["resultados"] == {} and vazio["amostras"] == []


def test_resultado_de_exame_invalido_aponta_o_campo(app):
    with app.app_context(), pytest.raises(CampoInvalido) as erro:
        coletar_respostas_pre_t0(_form(prnt_resultado__res__s1="9"))
    assert erro.value.campo == "prnt_resultado__res__s1"


def test_ficha_nao_mostra_sua_jornada_e_traz_resultados_por_exame(app):
    schema = carregar_esquema_pre_t0()
    with app.test_request_context("/x"):
        html = render_template("sfa/pre_t0_form.html", schema=schema, error="", submitted=MultiDict(), form_action="/x")
    assert "SUA JORNADA" not in html and "journey-card" not in html
    assert "ETAPA 01 DE 13" in html
    for exame in ("s1", "s2", "prnt"):
        assert f'name="prnt_resultado__res__{exame}"' in html
    assert 'name="logradouro"' in html and "paired-stacked" in html
