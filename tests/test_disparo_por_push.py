# -*- coding: utf-8 -*-
"""Disparar workflow sem o clique em "Run workflow".

Investigar producao e publicar dependiam de `workflow_dispatch` -- um clique na
interface do GitHub. Quem nao tem esse clique (um agente, ou alguem so com o
celular na mao) ficava parado esperando outra pessoa.

O contorno e um push numa branch dedicada. Quem pode empurrar a branch ja podia
rodar o workflow pelo formulario, entao a permissao e a mesma de sempre -- o
que muda e so o gesto.

O que estes testes travam:

- o caminho por push existe nos dois workflows, e em nenhum deles aponta para
  `main` (publicar a cada merge seria outra decisao, bem maior);
- a suite NAO e pulada fora do formulario. `inputs.run_tests` vem vazio num
  push, entao `if: ${{ inputs.run_tests }}` sozinho pularia a suite calado;
- o deploy por push so publica commit que ja esta em `main`. E esta a trava que
  torna o caminho seguro: empurrar escolhe QUANDO publicar, nunca O QUE.

Os workflows sao conferidos como texto, e nao com um parser de YAML, para nao
acrescentar uma dependencia a suite so por causa destes testes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.ler_pedido_logs import PedidoInvalido, ler_pedido


RAIZ = Path(__file__).resolve().parents[1]
WORKFLOWS = RAIZ / ".github" / "workflows"


def texto(nome):
    return (WORKFLOWS / nome).read_text(encoding="utf-8")


def bloco_do_passo(fonte, nome):
    """Devolve o trecho do YAML entre `- name: <nome>` e o proximo `- name:`."""
    inicio = re.search(rf"^      - name: {re.escape(nome)}$", fonte, re.M)
    assert inicio, f"passo {nome!r} nao encontrado"
    resto = fonte[inicio.end():]
    proximo = re.search(r"^      - name: ", resto, re.M)
    return resto[: proximo.start()] if proximo else resto


# --- gatilho --------------------------------------------------------------


@pytest.mark.parametrize(
    "arquivo,branch",
    [
        ("logs-heroku.yml", "disparo/logs-heroku"),
        ("deploy.yml", "disparo/deploy"),
    ],
)
def test_push_na_branch_dedicada_dispara_o_workflow(arquivo, branch):
    fonte = texto(arquivo)

    assert "workflow_dispatch:" in fonte, "o clique manual continua valendo"
    gatilho_push = re.search(r"^  push:\n    branches:\n      - (.+)$", fonte, re.M)
    assert gatilho_push, "falta o gatilho de push"
    assert gatilho_push.group(1).strip() == branch


@pytest.mark.parametrize("arquivo", ["logs-heroku.yml", "deploy.yml"])
def test_nenhum_dos_dois_dispara_em_main(arquivo):
    # Publicar a cada merge em main seria outra decisao, bem maior, e nao e
    # esta. O gesto continua sendo explicito.
    fonte = texto(arquivo)
    gatilho = re.search(r"^  push:\n    branches:\n((?:      - .+\n)+)", fonte, re.M)
    assert gatilho
    branches = {linha.strip(" -\n") for linha in gatilho.group(1).splitlines()}
    assert branches.isdisjoint({"main", "master"})


# --- travas do deploy -----------------------------------------------------


def test_deploy_por_push_exige_commit_que_ja_esta_em_main():
    passo = bloco_do_passo(texto("deploy.yml"), "Conferir que o commit ja passou por main")

    assert "github.event_name == 'push'" in passo
    # `--is-ancestor HEAD origin/main` e o que responde "este commit ja esta em
    # main?". Sem ele, a branch publicaria codigo sem revisao nenhuma.
    assert "git merge-base --is-ancestor HEAD origin/main" in passo
    assert "exit 1" in passo


def test_suite_nao_e_pulada_quando_o_disparo_nao_e_o_formulario():
    passo = bloco_do_passo(texto("deploy.yml"), "Suite de testes")

    # Num push, `inputs.run_tests` vem vazio: `if: ${{ inputs.run_tests }}`
    # sozinho pularia a suite inteira sem avisar ninguem.
    condicao = re.search(r"^        if: (.+)$", passo, re.M)
    assert condicao, "a suite precisa de uma condicao explicita"
    assert "github.event_name != 'workflow_dispatch'" in condicao.group(1)
    assert "inputs.run_tests" in condicao.group(1)


def test_deploy_por_push_publica_o_proprio_commit_empurrado():
    passo = bloco_do_passo(texto("deploy.yml"), "Checkout")
    assert "ref: ${{ inputs.ref || github.sha }}" in passo


def test_travas_antigas_do_deploy_seguem_de_pe():
    fonte = texto("deploy.yml")

    for esperado in (
        "Preflight de deploy",
        "Suite de testes",
        "Guarda de artefatos sensiveis",
        "Esperar o release phase",
    ):
        assert f"- name: {esperado}" in fonte

    publicar = bloco_do_passo(fonte, "Publicar")
    assert "git merge-base --is-ancestor heroku/main HEAD" in publicar
    # So os comandos: o passo explica em comentario por que nao usa --force, e
    # a palavra no comentario nao pode fazer o teste passar nem reprovar.
    comandos = [
        linha for linha in publicar.splitlines() if linha.strip() and not linha.strip().startswith("#")
    ]
    assert not [linha for linha in comandos if "--force" in linha], (
        "push forcado apagaria correcao feita por fora"
    )


@pytest.mark.parametrize("arquivo", ["logs-heroku.yml", "deploy.yml"])
def test_workflows_nao_ganham_permissao_de_escrita(arquivo):
    assert "permissions:\n  contents: read\n" in texto(arquivo)


def test_logs_seguem_sem_publicar_nada():
    fonte = texto("logs-heroku.yml")
    assert "git push" not in fonte
    assert "deploy" not in fonte.lower().replace("disparo/logs-heroku", "")


# --- leitura do pedido ----------------------------------------------------


def test_pedido_ausente_vira_as_ultimas_linhas_sem_filtro(tmp_path):
    assert ler_pedido(tmp_path / "nao-existe.json") == {"filtro": "", "linhas": 500}


def test_pedido_valido_e_lido(tmp_path):
    arquivo = tmp_path / "logs.json"
    arquivo.write_text(json.dumps({"filtro": "animal.*photo", "linhas": 120}), encoding="utf-8")

    assert ler_pedido(arquivo) == {"filtro": "animal.*photo", "linhas": 120}


def test_regex_quebrada_e_recusada_com_explicacao(tmp_path):
    arquivo = tmp_path / "logs.json"
    arquivo.write_text(json.dumps({"filtro": "animal(["}), encoding="utf-8")

    with pytest.raises(PedidoInvalido) as exc:
        ler_pedido(arquivo)
    # Melhor recusar aqui do que ver o job quebrar la dentro com uma mensagem
    # do `re` sem contexto nenhum.
    assert "expressao regular" in str(exc.value)


@pytest.mark.parametrize("linhas", [0, -1, 99999, "muitas"])
def test_quantidade_de_linhas_fora_do_razoavel_e_recusada(tmp_path, linhas):
    arquivo = tmp_path / "logs.json"
    arquivo.write_text(json.dumps({"linhas": linhas}), encoding="utf-8")

    with pytest.raises(PedidoInvalido):
        ler_pedido(arquivo)


def test_json_quebrado_e_recusado(tmp_path):
    arquivo = tmp_path / "logs.json"
    arquivo.write_text("{isto nao e json", encoding="utf-8")

    with pytest.raises(PedidoInvalido):
        ler_pedido(arquivo)


def test_pedido_versionado_no_repositorio_e_valido():
    # O arquivo que esta no repo precisa ser lido pelo proprio script: se
    # alguem o quebrar, o teste avisa antes do push disparar o workflow.
    pedido = ler_pedido(RAIZ / ".github" / "disparo" / "logs.json")
    assert pedido["linhas"] > 0
