# -*- coding: utf-8 -*-
"""Publicar nao pode depender de configuracao que so existe no computador.

Exigir o nome do app numa variavel tornava o deploy impossivel de configurar
pelo celular: o app do GitHub nao abre as configuracoes do repositorio, e o
nome saia de um `git remote` que so existe na maquina de quem programa. O
token, que ja esta configurado, sabe quais apps a conta tem.
"""

from __future__ import annotations

import pytest

from scripts.resolve_heroku_app import AppIndefinido, resolve_app


def test_conta_com_um_app_dispensa_configuracao():
    assert resolve_app("", ["petorlandia"]) == "petorlandia"


def test_nome_pedido_no_disparo_tem_prioridade():
    assert resolve_app("staging", ["petorlandia", "staging"]) == "staging"


def test_varios_apps_sem_escolha_lista_as_opcoes():
    with pytest.raises(AppIndefinido) as erro:
        resolve_app("", ["staging", "petorlandia"])

    mensagem = str(erro.value)
    # A mensagem precisa dizer o que fazer e quais sao as opcoes.
    assert "Run workflow" in mensagem
    assert "petorlandia" in mensagem and "staging" in mensagem


def test_app_que_a_conta_nao_enxerga_falha_antes_do_push():
    with pytest.raises(AppIndefinido) as erro:
        resolve_app("outro-app", ["petorlandia"])
    assert "nao tem o app 'outro-app'" in str(erro.value)


def test_token_sem_nenhum_app_explica_o_motivo():
    with pytest.raises(AppIndefinido) as erro:
        resolve_app("", [])
    assert "expirou" in str(erro.value)


def test_nome_pedido_passa_quando_a_listagem_falhou():
    # Sem listagem (conta sem permissao de listar), confiar no que foi pedido
    # e melhor do que travar um deploy que funcionaria.
    assert resolve_app("petorlandia", []) == "petorlandia"
